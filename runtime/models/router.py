"""Model router and budgeted client (spec 6.5, 7.2, 7.3, 7.4; AT-011/AT-012.2).

Selection filters first by capability, privacy/consent, availability and budget, then chooses by
mode and complexity. A model is usable only after it was validated against the owner's account
("Testar inteligência"); catalog presence is not access. Fallback on 429/unavailability stays with
compatible models of the same provider unless the owner consented to cross-provider fallback AND
to sharing data with that provider. Credential errors ask for re-authorization; provider policy
refusals are never routed around. A model call never grants permissions.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta

from runtime.models.pricing import PriceTable
from runtime.models.types import (
    Billing,
    ModelCapabilities,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderCallError,
    ProviderErrorKind,
    Usage,
)
from runtime.tasks.limits import CircuitBreaker
from security.budget.budget import BudgetManager
from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.money import Money
from storage import journal
from storage.db import transaction

MODES = ("automatic", "economic", "max_quality", "manual")


@dataclass(frozen=True)
class CatalogEntry:
    provider: str
    model_id: str
    profile: str  # general | deep | light | ...
    quality_rank: int  # higher = more capable (from Atlas evaluations, not self-assessment)
    capabilities: ModelCapabilities
    validated: bool = False  # set only by a successful, owner-authorized "Testar inteligência"


@dataclass(frozen=True)
class Requirements:
    structured_output: bool = False
    tool_calls: bool = False
    vision: bool = False
    data_classification: str = "INTERNAL"
    complexity: str = "normal"  # light | normal | hard


@dataclass
class Consent:
    """Owner consent, recorded outside the model. Nothing here can be set by model output."""

    providers_allowed: set[str] = field(default_factory=set)
    sensitive_data_providers: set[str] = field(default_factory=set)
    cross_provider_fallback: bool = False


class ModelRouter:
    def __init__(
        self,
        catalog: list[CatalogEntry],
        consent: Consent,
        mode: str = "automatic",
        manual_model: str | None = None,
        primary_provider: str = "openai",
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode}")
        if mode == "manual" and not manual_model:
            raise ValueError("manual mode needs an explicit model")
        self.catalog = catalog
        self.consent = consent
        self.mode = mode
        self.manual_model = manual_model
        # Spec 7.1: one primary provider; others are secondary and used only as consented fallback.
        self.primary_provider = primary_provider

    def candidates(self, req: Requirements, unavailable: set[str] | None = None) -> list[CatalogEntry]:
        if req.data_classification == "SECRET":
            raise AtlasError(ErrorCode.POLICY_DENIED, "SECRET data is never sent to a model provider")
        unavailable = unavailable or set()
        out: list[CatalogEntry] = []
        for e in self.catalog:
            c = e.capabilities
            if not e.validated or e.provider not in self.consent.providers_allowed:
                continue
            if (
                req.data_classification == "SENSITIVE"
                and e.provider not in self.consent.sensitive_data_providers
            ):
                continue
            if (req.structured_output and not c.structured_output) or (req.tool_calls and not c.tool_calls):
                continue
            if req.vision and not c.vision:
                continue
            if f"{e.provider}/{e.model_id}" in unavailable:
                continue
            out.append(e)
        if self.mode == "manual":
            out = [e for e in out if e.model_id == self.manual_model]
        elif self.mode == "economic":
            out.sort(key=lambda e: e.quality_rank)
        elif self.mode == "max_quality":
            out.sort(key=lambda e: -e.quality_rank)
        else:  # automatic: light tasks prefer light models, hard tasks prefer the strongest
            if req.complexity == "light":
                out.sort(key=lambda e: e.quality_rank)
            elif req.complexity == "hard":
                out.sort(key=lambda e: -e.quality_rank)
            else:
                out.sort(key=lambda e: (e.profile != "general", -e.quality_rank))
        out.sort(
            key=lambda e: e.provider != self.primary_provider
        )  # stable: keeps mode order within provider
        if not out:
            raise AtlasError(
                ErrorCode.MODEL_UNSUPPORTED,
                "no validated, consented model meets the requirements",
                recommended_action="run 'Testar inteligência' or adjust consent/configuration",
            )
        return out

    def fallback_allowed(self, primary: CatalogEntry, candidate: CatalogEntry) -> bool:
        if candidate.provider == primary.provider:
            return True
        return self.consent.cross_provider_fallback and candidate.provider in self.consent.providers_allowed


@dataclass(frozen=True)
class CallScope:
    """Who a billable call is for: a task, or an employee-level purpose (conversation, check)."""

    task_id: str | None
    employee_id: str | None
    purpose: str = "task"


class BudgetedModelClient:
    """Reserve, record the attempt, call, then settle by confirmed usage (spec 7.4; finding R-04).

    The attempt row and its reservation are committed before the request is sent. Outcomes:
    * proven not sent / not billed -> reservation RELEASED;
    * usage reported -> SETTLED at the real cost (overruns are recorded, never hidden);
    * response without usage -> ESTIMATED at the reserved maximum, reconcilable later;
    * anything uncertain (transport error, timeout, cancellation, 5xx) -> UNKNOWN, reservation held.
    A crash between response and commit leaves IN_FLIGHT, which ``recover_attempts`` turns into
    UNKNOWN. UNKNOWN attempts are resolved with evidence or, after the retention window, settled
    conservatively at the reserved amount with an auditable journal entry. There is no blanket
    ``finally`` that releases reservations.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        router: ModelRouter,
        providers: dict[str, ModelProvider],
        prices: PriceTable,
        budget: BudgetManager,
        breakers: dict[str, CircuitBreaker] | None = None,
        unknown_retention: timedelta = timedelta(days=7),
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.router = router
        self.providers = providers
        self.prices = prices
        self.budget = budget
        self.breakers = breakers or {}
        self.unknown_retention = unknown_retention

    # ---------------------------------------------------------------- attempt bookkeeping

    def _open_attempt(self, scope: CallScope, entry: CatalogEntry, amount: Money) -> tuple[str, str]:
        with transaction(self.conn):
            reservation = self.budget.reserve_in_txn(
                task_id=scope.task_id, category="inference", amount=amount
            )
            attempt_id = new_id()
            self.conn.execute(
                "INSERT INTO inference_attempts(id, task_id, employee_id, purpose, reservation_id, provider, model_id,"
                " status, created_at) VALUES (?,?,?,?,?,?,?,'IN_FLIGHT',?)",
                (
                    attempt_id,
                    scope.task_id,
                    scope.employee_id,
                    scope.purpose,
                    reservation.id,
                    entry.provider,
                    entry.model_id,
                    to_utc_str(self.clock.now()),
                ),
            )
        return attempt_id, reservation.id

    def _close_in_txn(
        self, attempt_id: str, status: str, diagnostic: str, request_id: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE inference_attempts SET status = ?, diagnostic = ?, request_id = COALESCE(?, request_id),"
            " closed_at = ? WHERE id = ?",
            (status, diagnostic[:500], request_id, to_utc_str(self.clock.now()), attempt_id),
        )

    def _journal(self, scope: CallScope, type_: str, summary: str) -> None:
        employee_id = scope.employee_id
        if employee_id is None:
            employee_id = self.conn.execute(
                "SELECT employee_id FROM tasks WHERE id = ?", (scope.task_id,)
            ).fetchone()[0]
        journal.append(
            self.conn,
            self.clock,
            employee_id=employee_id,
            task_id=scope.task_id,
            type=type_,
            actor=Actor("control_plane", "model-client", "internal"),
            summary=summary,
        )

    def _mark_unknown(self, scope: CallScope, attempt_id: str, why: str) -> None:
        with transaction(self.conn):
            self._close_in_txn(attempt_id, "UNKNOWN", why)
            self._journal(
                scope,
                "inference.billing_unknown",
                f"attempt {attempt_id}: {why}; reservation held for reconciliation",
            )

    # ---------------------------------------------------------------- call

    def call(
        self,
        *,
        task_id: str | None,
        req: Requirements,
        request: ModelRequest,
        employee_id: str | None = None,
        purpose: str = "task",
    ) -> ModelResponse:
        if task_id is None and employee_id is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "a model call needs a task or an employee scope")
        scope = CallScope(task_id, employee_id, purpose)
        tried: set[str] = set()
        primary: CatalogEntry | None = None
        last_error: AtlasError | None = None
        for _attempt in range(3):
            try:
                candidates = self.router.candidates(req, unavailable=tried)
            except AtlasError as exc:
                raise last_error or exc from None
            entry = next(
                (c for c in candidates if primary is None or self.router.fallback_allowed(primary, c)), None
            )
            if entry is None:
                break
            primary = primary or entry
            tried.add(f"{entry.provider}/{entry.model_id}")
            breaker = self.breakers.setdefault(entry.provider, CircuitBreaker(self.clock))
            if not breaker.allow():
                last_error = AtlasError(ErrorCode.PROVIDER_UNAVAILABLE, f"circuit open for {entry.provider}")
                continue
            provider = self.providers[entry.provider]
            price = self.prices.get(entry.provider, entry.model_id)
            call_req = ModelRequest(
                entry.model_id,
                request.messages,
                request.max_output_tokens,
                request.json_schema if entry.capabilities.structured_output else None,
                request.effort if request.effort in entry.capabilities.effort_levels else None,
                request.timeout_s,
            )
            estimate = provider.estimate_usage(call_req)
            reserve_amount = price.max_cost(estimate.input_tokens, call_req.max_output_tokens)
            attempt_id, reservation_id = self._open_attempt(
                scope, entry, reserve_amount
            )  # BudgetError propagates

            try:
                response = provider.generate(call_req)
            except ProviderCallError as exc:
                breaker.failure()
                if exc.sent is False:
                    with transaction(self.conn):
                        self.budget.release_in_txn(reservation_id)
                        self._close_in_txn(attempt_id, "RELEASED", f"not sent: {exc}")
                else:
                    self._mark_unknown(scope, attempt_id, f"{exc.kind}: {exc} (sent={exc.sent})")
                if exc.kind == ProviderErrorKind.CANCELLED:
                    raise AtlasError(
                        ErrorCode.PROVIDER_UNAVAILABLE,
                        "model call cancelled",
                        persisted="attempt recorded; billing reconciled later",
                    ) from exc
                last_error = AtlasError(ErrorCode.PROVIDER_UNAVAILABLE, str(exc))
                continue
            except Exception as exc:  # unexpected adapter bug: cannot know if it was sent
                self._mark_unknown(scope, attempt_id, f"adapter raised {type(exc).__name__}")
                raise AtlasError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"model adapter failed: {type(exc).__name__}",
                    persisted="attempt recorded as UNKNOWN; reservation held",
                ) from exc

            if response.error is not None:
                billing = response.error.effective_billing
                kind = response.error.kind
                with transaction(self.conn):
                    if response.usage is not None:
                        self.budget.settle_in_txn(reservation_id, price.cost(response.usage))
                        self._close_in_txn(
                            attempt_id, "SETTLED", f"{kind} with reported usage", response.request_id
                        )
                    elif billing == Billing.NONE:
                        self.budget.release_in_txn(reservation_id)
                        self._close_in_txn(attempt_id, "RELEASED", f"{kind}: not billed", response.request_id)
                    else:
                        self._close_in_txn(
                            attempt_id, "UNKNOWN", f"{kind}: billing {billing}", response.request_id
                        )
                        self._journal(
                            scope,
                            "inference.billing_unknown",
                            f"attempt {attempt_id}: {kind}; reservation held for reconciliation",
                        )
                if kind in (ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.UNAVAILABLE):
                    breaker.failure()
                    last_error = AtlasError(
                        ErrorCode.RATE_LIMITED
                        if kind == ProviderErrorKind.RATE_LIMITED
                        else ErrorCode.PROVIDER_UNAVAILABLE,
                        response.error.message,
                    )
                    continue
                if kind == ProviderErrorKind.AUTH:
                    raise AtlasError(
                        ErrorCode.UNAUTHORIZED,
                        "provider credential rejected",
                        recommended_action="ask the owner to re-authorize this provider",
                    )
                if kind == ProviderErrorKind.POLICY:
                    raise AtlasError(ErrorCode.POLICY_DENIED, "provider refused the request; not rerouting")
                raise AtlasError(ErrorCode.MODEL_UNSUPPORTED, response.error.message)

            breaker.success()
            with transaction(self.conn):
                if response.usage is not None:
                    usage = response.usage
                    cost = price.cost(usage)
                    status, diag = "SETTLED", "usage reported"
                    if cost.amount_minor > reserve_amount.amount_minor:
                        diag = f"cost {cost.amount_minor} exceeded reservation {reserve_amount.amount_minor}"
                        self._journal(scope, "budget.overrun", f"attempt {attempt_id}: {diag}")
                else:
                    usage = estimate
                    cost = reserve_amount
                    status, diag = "ESTIMATED", "provider reported no usage; settled at reserved maximum"
                self.budget.settle_in_txn(reservation_id, cost)
                self._close_in_txn(attempt_id, status, diag, response.request_id)
                self._record_usage(
                    scope.task_id,
                    entry,
                    response,
                    usage,
                    reserve_amount.amount_minor,
                    cost.amount_minor,
                    cost.currency,
                    reservation_id,
                )
            return ModelResponse(
                response.provider,
                response.model_id,
                response.request_id,
                response.output_text,
                response.proposed_tool_calls,
                response.finish_reason,
                usage,
                cost,
            )
        raise last_error or AtlasError(ErrorCode.PROVIDER_UNAVAILABLE, "no compatible model available")

    # ---------------------------------------------------------------- recovery and reconciliation

    def recover_attempts(self) -> list[str]:
        """After a restart, IN_FLIGHT attempts cannot be known: mark them UNKNOWN (reservation held)."""
        rows = self.conn.execute(
            "SELECT id, task_id, employee_id, purpose FROM inference_attempts WHERE status = 'IN_FLIGHT'"
        ).fetchall()
        for r in rows:
            self._mark_unknown(
                CallScope(r["task_id"], r["employee_id"], r["purpose"]),
                r["id"],
                "interrupted before the outcome was committed",
            )
        return [r["id"] for r in rows]

    def resolve_attempt(self, attempt_id: str, *, actor: Actor, charged: Money | None, evidence: str) -> str:
        """Resolve UNKNOWN/ESTIMATED with evidence (e.g. provider usage export). ``charged=None`` means
        the evidence shows no charge."""
        if actor.kind not in ("owner", "control_plane"):
            raise AtlasError(
                ErrorCode.UNAUTHORIZED, "only the owner or a trusted reconciler resolves billing"
            )
        if not evidence.strip():
            raise AtlasError(ErrorCode.INVALID_INPUT, "resolution requires evidence")
        row = self.conn.execute("SELECT * FROM inference_attempts WHERE id = ?", (attempt_id,)).fetchone()
        if row is None or row["status"] not in ("UNKNOWN", "ESTIMATED"):
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "attempt is not awaiting reconciliation")
        with transaction(self.conn):
            if row["status"] == "UNKNOWN":
                if charged is None:
                    self.budget.release_in_txn(row["reservation_id"])
                else:
                    self.budget.settle_in_txn(row["reservation_id"], charged)
            else:  # ESTIMATED: correct the settled amount to the real charge
                self.conn.execute(
                    "UPDATE budget_reservations SET settled_minor = ? WHERE id = ?",
                    (charged.amount_minor if charged else 0, row["reservation_id"]),
                )
            self._close_in_txn(attempt_id, "RESOLVED", f"resolved by {actor.kind}: {evidence}")
            self._journal(
                CallScope(row["task_id"], row["employee_id"], row["purpose"]),
                "inference.reconciled",
                f"attempt {attempt_id} resolved: {'charged' if charged else 'no charge'}",
            )
        return "RESOLVED"

    def expire_unknown(self) -> list[str]:
        """Retention policy: UNKNOWN older than the window is settled conservatively at the reserved
        amount (never released blindly) and journaled, so reservations do not stay open forever."""
        cutoff = self.clock.now() - self.unknown_retention
        expired = []
        for r in self.conn.execute(
            "SELECT a.id, a.task_id, a.employee_id, a.purpose, a.reservation_id, a.created_at, b.amount_minor,"
            " b.currency"
            " FROM inference_attempts a JOIN budget_reservations b ON b.id = a.reservation_id"
            " WHERE a.status = 'UNKNOWN'"
        ).fetchall():
            if parse_utc(r["created_at"]) > cutoff:
                continue
            with transaction(self.conn):
                self.budget.settle_in_txn(r["reservation_id"], Money(r["amount_minor"], r["currency"]))
                self._close_in_txn(
                    r["id"],
                    "RESOLVED",
                    f"retention window {self.unknown_retention} elapsed: settled at reserved maximum",
                )
                self._journal(
                    CallScope(r["task_id"], r["employee_id"], r["purpose"]),
                    "inference.reconciled",
                    f"attempt {r['id']} settled conservatively after retention window",
                )
            expired.append(r["id"])
        return expired

    def _record_usage(
        self,
        task_id: str | None,
        entry: CatalogEntry,
        resp: ModelResponse,
        usage: Usage,
        estimated_minor: int,
        reported_minor: int,
        currency: str,
        reservation_id: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO usage_ledger(id, reservation_id, task_id, provider, model_id, request_id, category,"
            " input_tokens, cached_tokens, output_tokens, estimated_minor, reported_minor, currency, price_table,"
            " created_at) VALUES (?,?,?,?,?,?,'inference',?,?,?,?,?,?,?,?)",
            (
                new_id(),
                reservation_id,
                task_id,
                entry.provider,
                resp.model_id,
                resp.request_id,
                usage.input_tokens,
                usage.cached_input_tokens,
                usage.output_tokens,
                estimated_minor,
                reported_minor,
                currency,
                self.prices.version,
                to_utc_str(self.clock.now()),
            ),
        )
