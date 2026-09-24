"""Dispatch broker - the Control Plane's single door to external effects (spec 4.3, 11, 12, 13.6).

The LLM proposes; the broker validates and executes. For every proposal:

Phase 1 (one transaction): validate the ActionProposal contract and the tool input; resolve the
tool in the trusted registry; verify lease + fencing token; evaluate policy; handle approval or
mandate; reserve budget; move the ledger PROPOSED -> AUTHORIZED -> DISPATCHING. Nothing leaves the
machine before this commits.

Phase 2 (no transaction): run the trusted adapter. Credentials are released by the Vault only
for the tool's declared purpose and the action's destination.

Phase 3 (one transaction): settle. CONFIRMED needs the verification the manifest requires (e.g. a
provider receipt); a bare success flag is not proof. FAILED is accepted only when the trusted
adapter asserts the effect did not happen. Anything else is UNKNOWN: the approval stays held,
the budget stays reserved and the task is BLOCKED(EXTERNAL_EFFECT_UNKNOWN) until reconciliation.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from runtime.tasks.engine import Lease, TaskEngine
from runtime.tasks.state_machine import TaskState
from runtime.tools.registry import RegistryError, ToolManifest, ToolRegistry
from security.approvals.engine import ApprovalEngine
from security.approvals.mandates import MandateStore
from security.broker.executor import DEFAULT_GRACE_S, run_in_process, run_in_thread
from security.broker.ledger import Ledger
from security.budget.budget import BudgetError, BudgetManager
from security.policy.engine import MandateView, Outcome, PolicyEngine, PolicyRequest
from security.vault.vault import SecretValue, Vault, VaultError
from shared.actors import Actor
from shared.canonical import canonical_hash
from shared.clock import Clock, parse_utc, to_utc_str
from shared.contracts import errors_for, validate
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.money import Money, MoneyError
from storage import journal
from storage.db import transaction

BROKER = Actor("control_plane", "broker", "internal")
EVIDENCE_KINDS = {
    "provider_receipt",
    "artifact_hash",
    "file_opens",
    "deterministic_check",
    "source_check",
    "human_confirmation",
}


@dataclass
class AdapterOutcome:
    """What a trusted adapter reports. The broker turns it into a validated ToolResult."""

    status: str  # SUCCEEDED | FAILED | UNKNOWN
    external_reference: str | None = None
    receipt: dict[str, Any] | None = None
    error_message: str | None = None
    retryable: bool = False
    reported_cost: Money | None = None
    output: dict[str, Any] | None = None  # untrusted content, never instructions


@dataclass
class DispatchResult:
    status: str  # CONFIRMED | FAILED | UNKNOWN | APPROVAL_REQUIRED | DENIED | REJECTED | BUDGET_EXCEEDED
    action_id: str | None
    reason: str
    approval: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


class ToolContext:
    """Handed to adapters. Holds at most one secret, released by the Vault in the broker thread for
    the tool's declared purpose and this action's destination. Adapters must honour ``cancelled``."""

    def __init__(
        self,
        manifest: ToolManifest,
        action_id: str,
        destination: str | None,
        idempotency_key: str | None,
        deadline_s: float,
        secret: SecretValue | None = None,
    ) -> None:
        self._manifest = manifest
        self.action_id = action_id
        self.destination = destination
        self.idempotency_key = idempotency_key
        self.deadline_s = deadline_s
        self.cancel_event = threading.Event()
        self._secret = secret

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def secret(self) -> SecretValue:
        if self._secret is None:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "this tool has no credential for this destination")
        if self.cancelled:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "action was cancelled; credential withdrawn")
        return self._secret

    def close(self) -> None:
        self._secret = None


_INFLIGHT: dict[str, tuple[str, ToolContext]] = {}
_INFLIGHT_LOCK = threading.Lock()


class Broker:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        *,
        registry: ToolRegistry,
        policy: PolicyEngine,
        budget: BudgetManager,
        owner_channels: frozenset[str] = frozenset(),
        vault: Vault | None = None,
        grace_s: float = DEFAULT_GRACE_S,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.registry = registry
        self.policy = policy
        self.budget = budget
        self.owner_channels = owner_channels
        self.vault = vault
        self.tasks = TaskEngine(conn, clock)
        self.approvals = ApprovalEngine(conn, clock)
        self.mandates = MandateStore(conn, clock)
        self.ledger = Ledger(conn, clock)
        self.grace_s = grace_s
        # Process-wide: a stop received on one IPC connection must reach work running in the worker.
        self._inflight = _INFLIGHT
        self._inflight_lock = _INFLIGHT_LOCK
        self._late: queue.Queue[tuple[str, AdapterOutcome]] = queue.Queue()

    # ================================================================== submit

    def submit(self, proposal: dict[str, Any], lease: Lease) -> DispatchResult:
        # --- contract and trusted registry (no writes yet)
        errs = errors_for("action_proposal", proposal)
        if errs:
            raise AtlasError(ErrorCode.INVALID_INPUT, "invalid ActionProposal: " + "; ".join(errs[:3]))
        if proposal["task_id"] != lease.task_id:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "proposal task does not match the worker lease")
        try:
            manifest, adapter = self.registry.resolve(proposal["tool_id"], proposal["tool_version"])
        except RegistryError as exc:
            self._journal_rejection(lease, f"tool refused: {exc}")
            raise AtlasError(ErrorCode.POLICY_DENIED, f"tool not available: {exc}") from exc
        tool_input: dict[str, Any] = proposal["input"]
        input_errors = sorted(
            e.message for e in Draft202012Validator(manifest.input_schema).iter_errors(tool_input)
        )
        if input_errors:
            raise AtlasError(ErrorCode.INVALID_INPUT, "tool input invalid: " + "; ".join(input_errors[:3]))
        destination = self._destination(manifest, tool_input)
        cost = self._cost(manifest, tool_input)
        input_hash = canonical_hash(
            {"tool_id": manifest.tool_id, "tool_version": manifest.version, "input": tool_input}
        )

        # --- phase 1: authorize and mark DISPATCHING atomically
        try:
            with transaction(self.conn):
                task = self.tasks.check_lease_in_txn(lease.task_id, lease.worker_id, lease.fencing_token)
                early = self._authorize_in_txn(
                    task, lease, proposal, manifest, tool_input, input_hash, destination, cost
                )
                if isinstance(early, DispatchResult):
                    return early
                action_id, idem_key, warnings = early
        except AtlasError as exc:
            if exc.code in (ErrorCode.UNAUTHORIZED, ErrorCode.VERSION_CONFLICT):
                self._journal_rejection(lease, str(exc))
            raise

        # --- phase 2: execute outside the transaction, under a deadline (review finding R-03)
        started = time.perf_counter()
        outcome = self._execute(
            manifest, adapter, tool_input, action_id, lease.task_id, destination, idem_key
        )
        duration_ms = int((time.perf_counter() - started) * 1000)

        # --- phase 3: settle
        result = self._settle(action_id, manifest, outcome, cost, duration_ms, lease)
        result.warnings = warnings
        return result

    # ------------------------------------------------------------------ execution

    def _release_secret(self, manifest: ToolManifest, destination: str | None) -> SecretValue | None:
        if manifest.credential_purpose is None:
            return None
        if self.vault is None or destination is None:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "credential required but no vault/destination available")
        ref_id = self.vault.find_ref(purpose=manifest.credential_purpose, destination=destination)
        with self.vault.use(
            ref_id, actor=BROKER, purpose=manifest.credential_purpose, destination=destination
        ) as secret:
            return SecretValue(secret.reveal())

    @staticmethod
    def _to_outcome(manifest: ToolManifest, value: Any, error: BaseException | None) -> AdapterOutcome:
        if error is not None:
            return AdapterOutcome(
                status="FAILED" if manifest.effect_class == "READ_ONLY" else "UNKNOWN",
                error_message=f"adapter raised {type(error).__name__}",
                retryable=manifest.effect_class == "READ_ONLY",
            )
        if isinstance(value, AdapterOutcome):
            return value
        try:
            return AdapterOutcome(**value)
        except TypeError:
            return AdapterOutcome(status="UNKNOWN", error_message="adapter returned an invalid outcome")

    def _execute(
        self,
        manifest: ToolManifest,
        adapter: Any,
        tool_input: dict[str, Any],
        action_id: str,
        task_id: str,
        destination: str | None,
        idem_key: str | None,
    ) -> AdapterOutcome:
        # Any write (local or external) interrupted by the deadline may already have happened.
        external = manifest.effect_class != "READ_ONLY"
        if manifest.isolation == "process":
            rep = run_in_process(adapter, tool_input, timeout_s=manifest.timeout_s)
            if rep.finished:
                return self._to_outcome(manifest, rep.value, rep.error)
            return AdapterOutcome(
                status="UNKNOWN" if external else "FAILED",
                error_message="DEADLINE_EXCEEDED: tool process terminated",
                retryable=not external,
            )
        try:
            secret = self._release_secret(manifest, destination)
        except (AtlasError, VaultError) as exc:
            return AdapterOutcome(status="FAILED", error_message=f"credential unavailable: {exc}")
        ctx = ToolContext(manifest, action_id, destination, idem_key, float(manifest.timeout_s), secret)
        with self._inflight_lock:
            self._inflight[action_id] = (task_id, ctx)

        def on_late(value: Any, error: BaseException | None) -> None:
            ctx.close()
            self._late.put((action_id, self._to_outcome(manifest, value, error)))

        try:
            rep = run_in_thread(
                lambda: adapter(tool_input, ctx),
                timeout_s=manifest.timeout_s,
                cancel_event=ctx.cancel_event,
                grace_s=self.grace_s,
                on_late=on_late,
            )
        finally:
            with self._inflight_lock:
                self._inflight.pop(action_id, None)
        if rep.finished:
            ctx.close()
            return self._to_outcome(manifest, rep.value, rep.error)
        return AdapterOutcome(
            status="UNKNOWN" if external else "FAILED",
            error_message="DEADLINE_EXCEEDED: adapter did not finish; a late result is recorded if it arrives",
            retryable=not external,
        )

    def request_cancel(self, task_id: str) -> list[str]:
        """Ask in-flight operations of a task to stop.

        Thread-safe and DB-free, so the owner's stop reaches an action that is already running. Whether
        the effect happened is still decided by the adapter's report or by reconciliation, never assumed.
        """
        hit: list[str] = []
        with self._inflight_lock:
            for action_id, (tid, ctx) in self._inflight.items():
                if tid == task_id:
                    ctx.cancel_event.set()
                    hit.append(action_id)
        return hit

    def collect_late_results(self) -> list[tuple[str, str]]:
        """Record results that arrived after the deadline (call from the broker's own thread).

        A late trusted report resolves an UNKNOWN action like reconciliation evidence. It never
        re-enables the worker: the task needs a valid state and a fresh lease for any further step.
        """
        done: list[tuple[str, str]] = []
        while True:
            try:
                action_id, outcome = self._late.get_nowait()
            except queue.Empty:
                return done
            action = self.ledger.get(action_id)
            manifest, _ = self.registry.resolve(action["tool_id"], action["tool_version"])
            if action["status"] != "UNKNOWN":
                done.append((action_id, f"ignored: action already {action['status']}"))
                continue
            receipt_ok = manifest.verification != "provider_receipt" or bool(outcome.external_reference)
            if outcome.status == "SUCCEEDED" and receipt_ok:
                final = self.reconcile(
                    action_id,
                    actor=BROKER,
                    happened=True,
                    evidence="late completion reported by the trusted adapter",
                    external_reference=outcome.external_reference,
                )
            elif outcome.status == "FAILED":
                final = self.reconcile(
                    action_id,
                    actor=BROKER,
                    happened=False,
                    evidence="late report from the trusted adapter: operation not performed",
                )
            else:
                final = "UNKNOWN"
            done.append((action_id, final))

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _destination(manifest: ToolManifest, tool_input: dict[str, Any]) -> str | None:
        if not manifest.destination_field:
            return None
        value = tool_input.get(manifest.destination_field)
        if not isinstance(value, str) or not value:
            raise AtlasError(ErrorCode.INVALID_INPUT, "destination missing from tool input")
        return value

    @staticmethod
    def _cost(manifest: ToolManifest, tool_input: dict[str, Any]) -> Money | None:
        if not manifest.cost_field:
            return None
        try:
            return Money.from_json(tool_input[manifest.cost_field])
        except (KeyError, TypeError, MoneyError) as exc:
            raise AtlasError(
                ErrorCode.INVALID_INPUT, "cost must be money with amount_minor and currency"
            ) from exc

    def _journal_rejection(self, lease: Lease, why: str) -> None:
        row = self.conn.execute("SELECT employee_id FROM tasks WHERE id = ?", (lease.task_id,)).fetchone()
        if row is None:
            return
        with transaction(self.conn):
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                task_id=lease.task_id,
                type="action.rejected",
                actor=Actor("worker", lease.worker_id, "internal"),
                summary=why[:900],
            )

    def _authorize_in_txn(
        self,
        task: sqlite3.Row,
        lease: Lease,
        proposal: dict[str, Any],
        manifest: ToolManifest,
        tool_input: dict[str, Any],
        input_hash: str,
        destination: str | None,
        cost: Money | None,
    ) -> DispatchResult | tuple[str, str | None, list[str]]:
        employee_id = task["employee_id"]
        worker = Actor("worker", lease.worker_id, "internal")
        if proposal["instruction_revision"] != task["instruction_revision"]:
            # Linearization point for corrections (A3-03): a proposal decided under older instructions
            # is refused inside the dispatch transaction, before anything is authorized or sent.
            raise AtlasError(
                ErrorCode.VERSION_CONFLICT,
                f"instructions changed (revision {proposal['instruction_revision']} -> "
                f"{task['instruction_revision']}); proposal discarded before dispatch",
                persisted="nothing dispatched",
                recommended_action="re-plan with the current instructions",
            )
        existing = self.ledger.find_open_in_txn(task["id"], input_hash)
        mandate = self.mandates.find_applicable_in_txn(
            employee_id=employee_id, tool_id=manifest.tool_id, destination=destination, cost=cost
        )
        decision = self.policy.evaluate(
            PolicyRequest(
                actor=worker,
                manifest=manifest,
                destination=destination,
                data_classification=task["data_policy"],
                cost=cost,
                task_constraints=json.loads(task["constraints_json"]),
                owner_channels=self.owner_channels,
                mandate=MandateView(mandate.id, mandate.max_risk) if mandate else None,
            )
        )
        if existing is not None:
            action_id = existing["id"]
        else:
            action_id = self.ledger.propose_in_txn(
                task_id=task["id"],
                step_id=proposal["step_id"],
                tool_id=manifest.tool_id,
                tool_version=manifest.version,
                effect_class=manifest.effect_class,
                risk_class=decision.risk_class,
                tool_input=tool_input,
                input_hash=input_hash,
                destination=destination,
                worker_id=lease.worker_id,
                instruction_revision=int(task["instruction_revision"]),
            )
        self.ledger.annotate_policy_in_txn(
            action_id, decision.outcome, decision.reason_code, decision.policy_version
        )

        def event(kind: str, summary: str) -> None:
            journal.append(
                self.conn,
                self.clock,
                employee_id=employee_id,
                task_id=task["id"],
                action_id=action_id,
                type=kind,
                actor=BROKER,
                policy_version=decision.policy_version,
                summary=summary,
            )

        if decision.outcome == Outcome.DENY:
            self.ledger.move_in_txn(
                action_id, "PROPOSED", "CANCELLED_BEFORE_DISPATCH", f"POLICY_DENIED:{decision.reason_code}"
            )
            event("action.denied", f"{manifest.tool_id} denied: {decision.reason_code}")
            return DispatchResult("DENIED", action_id, decision.reason_code)

        approval_id: str | None = None
        if decision.outcome == Outcome.ASK:
            approval = self.approvals.latest_for_action(action_id)
            if (
                approval is not None
                and approval["status"] in ("PENDING", "APPROVED")
                and (parse_utc(approval["expires_at"]) <= self.clock.now())
            ):
                self.approvals.expire_in_txn(approval["approval_id"])
                approval["status"] = "EXPIRED"
            if approval is None or approval["status"] in ("EXPIRED", "REVOKED"):
                purchase = None
                if manifest.purchase_fields:
                    purchase = {k: tool_input[k] for k in manifest.purchase_fields}
                approval = self.approvals.request_in_txn(
                    task_id=task["id"],
                    action_id=action_id,
                    employee_id=employee_id,
                    action_type=manifest.tool_id,
                    destination=destination or manifest.tool_id,
                    params_hash=input_hash,
                    max_cost=cost,
                    risk_class=decision.risk_class,
                    policy_version=decision.policy_version,
                    purchase=purchase,
                )
            if approval["status"] == "REJECTED":
                self.ledger.move_in_txn(
                    action_id, "PROPOSED", "CANCELLED_BEFORE_DISPATCH", "APPROVAL_REJECTED"
                )
                event("action.rejected_by_owner", f"{manifest.tool_id} rejected by owner")
                return DispatchResult("REJECTED", action_id, "APPROVAL_REJECTED", approval=approval)
            if approval["status"] == "PENDING":
                self.tasks.transition_in_txn(
                    task, TaskState.WAITING_APPROVAL, BROKER, f"approval needed for {manifest.tool_id}"
                )
                return DispatchResult("APPROVAL_REQUIRED", action_id, decision.reason_code, approval=approval)
            # APPROVED: reserve atomically against the exact hash
            self.approvals.reserve_in_txn(
                approval["approval_id"], action_id=action_id, params_hash=input_hash
            )
            approval_id = approval["approval_id"]

        mandate_id: str | None = None
        if decision.reason_code == "MANDATE_COVERS" and mandate is not None:
            self.mandates.consume_use_in_txn(mandate.id)
            mandate_id = mandate.id

        reservation_id: str | None = None
        warnings: list[str] = []
        if cost is not None and manifest.cost_category is not None:
            try:
                ceiling = None
                if manifest.cost_category == "purchase" and approval_id is not None:
                    ap = self.approvals.get(approval_id)
                    ceiling = Money.from_json(ap["max_cost"]) if ap["max_cost"] else None
                res = self.budget.reserve_in_txn(
                    task_id=task["id"], category=manifest.cost_category, amount=cost, purchase_ceiling=ceiling
                )
            except BudgetError as exc:
                if approval_id is not None:
                    self.approvals.release_in_txn(approval_id, action_id=action_id)
                self.ledger.move_in_txn(
                    action_id, "PROPOSED", "CANCELLED_BEFORE_DISPATCH", f"BUDGET:{exc.reason}"
                )
                self.tasks.transition_in_txn(
                    task, TaskState.BLOCKED, BROKER, f"budget: {exc.reason}", blocked_reason="BUDGET_EXCEEDED"
                )
                event("action.budget_blocked", f"{manifest.tool_id}: {exc.reason}")
                return DispatchResult("BUDGET_EXCEEDED", action_id, exc.reason)
            reservation_id = res.id
            warnings = res.warnings

        idem_key = action_id if manifest.supports_idempotency_key else None
        self.ledger.move_in_txn(
            action_id,
            "PROPOSED",
            "AUTHORIZED",
            decision.reason_code,
            approval_id=approval_id,
            mandate_id=mandate_id,
            budget_reservation_id=reservation_id,
        )
        self.ledger.move_in_txn(
            action_id,
            "AUTHORIZED",
            "DISPATCHING",
            None,
            fencing_token=lease.fencing_token,
            idempotency_key=idem_key,
            dispatched_at=to_utc_str(self.clock.now()),
        )
        event("action.dispatching", f"{manifest.tool_id} to {destination or '-'} ({decision.reason_code})")
        return action_id, idem_key, warnings

    # ------------------------------------------------------------------ settlement

    def _settle(
        self,
        action_id: str,
        manifest: ToolManifest,
        outcome: AdapterOutcome,
        cost: Money | None,
        duration_ms: int,
        lease: Lease,
    ) -> DispatchResult:
        status = outcome.status if outcome.status in ("SUCCEEDED", "FAILED", "UNKNOWN") else "UNKNOWN"
        reason = outcome.error_message or ""
        if (
            status == "SUCCEEDED"
            and manifest.verification == "provider_receipt"
            and not outcome.external_reference
        ):
            status, reason = "UNKNOWN", "success claimed without provider receipt"
        with transaction(self.conn):
            action = self.ledger.get(action_id)
            task = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (action["task_id"],)).fetchone()
            evidence_refs: list[str] = []
            if status == "SUCCEEDED":
                self.ledger.move_in_txn(
                    action_id,
                    "DISPATCHING",
                    "CONFIRMED",
                    "VERIFIED",
                    finished_at=to_utc_str(self.clock.now()),
                    external_reference=outcome.external_reference,
                )
                if outcome.external_reference:
                    self.ledger.record_receipt_in_txn(
                        action_id, outcome.external_reference, outcome.receipt or {}
                    )
                ev = new_id()
                kind = (
                    manifest.verification
                    if manifest.verification in EVIDENCE_KINDS
                    else "deterministic_check"
                )
                self.conn.execute(
                    "INSERT INTO evidence(id, task_id, action_id, kind, summary, created_at) VALUES (?,?,?,?,?,?)",
                    (
                        ev,
                        action["task_id"],
                        action_id,
                        kind,
                        f"{manifest.tool_id} confirmed"
                        + (f" ref {outcome.external_reference}" if outcome.external_reference else ""),
                        to_utc_str(self.clock.now()),
                    ),
                )
                evidence_refs.append(ev)
                if action["approval_id"]:
                    self.approvals.consume_in_txn(action["approval_id"], action_id=action_id)
                if action["budget_reservation_id"]:
                    self.budget.settle_in_txn(
                        action["budget_reservation_id"],
                        outcome.reported_cost or cost or Money(0, self.budget.limits.currency),
                    )
                final = "CONFIRMED"
            elif status == "FAILED":
                self.ledger.move_in_txn(
                    action_id,
                    "DISPATCHING",
                    "FAILED",
                    reason or "ADAPTER_REPORTED_FAILURE",
                    finished_at=to_utc_str(self.clock.now()),
                )
                if action["approval_id"]:
                    self.approvals.release_in_txn(action["approval_id"], action_id=action_id)
                if action["budget_reservation_id"]:
                    self.budget.release_in_txn(action["budget_reservation_id"])
                final = "FAILED"
            else:
                self.ledger.move_in_txn(
                    action_id,
                    "DISPATCHING",
                    "UNKNOWN",
                    reason or "OUTCOME_UNCONFIRMED",
                    external_reference=outcome.external_reference,
                )
                if action["approval_id"]:
                    self.approvals.hold_unknown_in_txn(action["approval_id"], action_id=action_id)
                # budget stays RESERVED on purpose: the provider may bill.
                still_ours = (
                    task["state"] == TaskState.RUNNING
                    and task["lease_owner"] == lease.worker_id
                    and task["fencing_token"] == lease.fencing_token
                )
                if still_ours:
                    self.tasks.transition_in_txn(
                        task,
                        TaskState.BLOCKED,
                        BROKER,
                        "external effect unknown",
                        blocked_reason="EXTERNAL_EFFECT_UNKNOWN",
                    )
                final = "UNKNOWN"
            tool_result = {
                "schema_version": "1.0",
                "action_id": action_id,
                "success": final == "CONFIRMED",
                "operation_status": {"CONFIRMED": "SUCCEEDED", "FAILED": "FAILED", "UNKNOWN": "UNKNOWN"}[
                    final
                ],
                "data_refs": [],
                "evidence_refs": evidence_refs,
                "external_reference": outcome.external_reference,
                "retry_class": {"CONFIRMED": "NONE", "UNKNOWN": "AFTER_RECONCILIATION"}.get(
                    final, "TRANSIENT" if outcome.retryable else "NEVER"
                ),
                "error": None
                if final == "CONFIRMED"
                else {
                    "code": "EXTERNAL_EFFECT_UNKNOWN" if final == "UNKNOWN" else "PROVIDER_UNAVAILABLE",
                    "message": (reason or final)[:2000],
                },
                "observability": {
                    "tool_id": manifest.tool_id,
                    "tool_version": manifest.version,
                    "duration_ms": duration_ms,
                },
            }
            validate("tool_result", tool_result)
            journal.append(
                self.conn,
                self.clock,
                employee_id=task["employee_id"],
                task_id=task["id"],
                action_id=action_id,
                type=f"action.{final.lower()}",
                actor=BROKER,
                duration_ms=duration_ms,
                evidence_refs=evidence_refs,
                summary=f"{manifest.tool_id}: {final}" + (f" ({reason})" if reason else ""),
            )
        return DispatchResult(
            final, action_id, reason or final, tool_result=tool_result, output=outcome.output
        )

    # ================================================================== owner-facing operations

    def decide_approval(
        self, approval_id: str, *, actor: Actor, approve: bool, params_hash: str, nonce: str
    ) -> dict[str, Any]:
        """Owner decision. Moves the task out of WAITING_APPROVAL so a worker can re-evaluate."""
        with transaction(self.conn):
            ap = self.approvals.decide_in_txn(
                approval_id, actor=actor, approve=approve, params_hash=params_hash, nonce=nonce
            )
            task = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (ap["task_id"],)).fetchone()
            if task["state"] == TaskState.WAITING_APPROVAL:
                self.tasks.transition_in_txn(task, TaskState.READY, actor, f"approval {ap['status'].lower()}")
        return ap

    def reconcile(
        self,
        action_id: str,
        *,
        actor: Actor,
        happened: bool,
        evidence: str,
        external_reference: str | None = None,
    ) -> str:
        """Resolve an UNKNOWN action with evidence from the external source of truth (spec 12.2).

        ``happened=False`` must mean *proven* not to have happened; when that cannot be proven the
        action stays UNKNOWN and a human is asked, instead of choosing an outcome at random.
        """
        if actor.kind not in ("owner", "control_plane"):
            raise AtlasError(ErrorCode.UNAUTHORIZED, "reconciliation needs the owner or a trusted reconciler")
        if not evidence.strip():
            raise AtlasError(ErrorCode.INVALID_INPUT, "reconciliation requires evidence")
        with transaction(self.conn):
            action = self.ledger.get(action_id)
            if action["status"] != "UNKNOWN":
                raise AtlasError(ErrorCode.VERSION_CONFLICT, f"action is {action['status']}, not UNKNOWN")
            ev = new_id()
            self.conn.execute(
                "INSERT INTO evidence(id, task_id, action_id, kind, summary, created_at) VALUES (?,?,?,?,?,?)",
                (
                    ev,
                    action["task_id"],
                    action_id,
                    "reconciliation",
                    evidence[:1000],
                    to_utc_str(self.clock.now()),
                ),
            )
            if happened:
                self.ledger.move_in_txn(
                    action_id,
                    "UNKNOWN",
                    "CONFIRMED",
                    "RECONCILED_HAPPENED",
                    finished_at=to_utc_str(self.clock.now()),
                    external_reference=external_reference or action["external_reference"],
                )
                if action["approval_id"]:
                    self.approvals.consume_in_txn(action["approval_id"], action_id=action_id)
                if action["budget_reservation_id"]:
                    r = self.conn.execute(
                        "SELECT amount_minor, currency FROM budget_reservations WHERE id = ?",
                        (action["budget_reservation_id"],),
                    ).fetchone()
                    self.budget.settle_in_txn(action["budget_reservation_id"], Money(r[0], r[1]))
                final = "CONFIRMED"
            else:
                self.ledger.move_in_txn(
                    action_id,
                    "UNKNOWN",
                    "FAILED",
                    "RECONCILED_NOT_HAPPENED",
                    finished_at=to_utc_str(self.clock.now()),
                )
                if action["approval_id"]:
                    self.approvals.release_in_txn(action["approval_id"], action_id=action_id)
                if action["budget_reservation_id"]:
                    self.budget.release_in_txn(action["budget_reservation_id"])
                final = "FAILED"
            task = self.conn.execute(
                "SELECT employee_id FROM tasks WHERE id = ?", (action["task_id"],)
            ).fetchone()
            journal.append(
                self.conn,
                self.clock,
                employee_id=task["employee_id"],
                task_id=action["task_id"],
                action_id=action_id,
                type="action.reconciled",
                actor=actor,
                evidence_refs=[ev],
                summary=f"UNKNOWN -> {final}",
            )
        self.tasks.unblock_if_resolved(action["task_id"], actor=actor)
        return final
