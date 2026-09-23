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

from runtime.models.pricing import PriceTable
from runtime.models.types import (
    ModelCapabilities,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderErrorKind,
    Usage,
)
from runtime.tasks.limits import CircuitBreaker
from security.budget.budget import BudgetManager
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
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


class BudgetedModelClient:
    """Reserve the maximum plausible cost, call, then settle with reported usage (spec 7.4)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        router: ModelRouter,
        providers: dict[str, ModelProvider],
        prices: PriceTable,
        budget: BudgetManager,
        breakers: dict[str, CircuitBreaker] | None = None,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.router = router
        self.providers = providers
        self.prices = prices
        self.budget = budget
        self.breakers = breakers or {}

    def call(self, *, task_id: str, req: Requirements, request: ModelRequest) -> ModelResponse:
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
            key = f"{entry.provider}/{entry.model_id}"
            tried.add(key)
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
            with transaction(self.conn):
                reservation = self.budget.reserve_in_txn(
                    task_id=task_id, category="inference", amount=reserve_amount
                )
            response = provider.generate(call_req)
            if response.error is not None:
                with transaction(self.conn):
                    self.budget.release_in_txn(reservation.id)
                kind = response.error.kind
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
            usage = response.usage or estimate
            cost = price.cost(usage)
            with transaction(self.conn):
                self.budget.settle_in_txn(reservation.id, cost)
                self._record_usage(
                    task_id,
                    entry,
                    response,
                    usage,
                    reserve_amount.amount_minor,
                    cost.amount_minor,
                    cost.currency,
                    reservation.id,
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

    def _record_usage(
        self,
        task_id: str,
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
