"""Agent loop - planner/executor/verifier cycle (spec 6.2, 9, 15; AT-016, review Etapa 3).

objective -> constraints -> relevant memories -> persisted plan -> ONE proposed step -> broker ->
observed result -> verification -> bounded replanning -> delivery.

The model only proposes the next decision as strict JSON. Tools run exclusively through the broker
with this worker's lease (so pause/stop/cancel revoke it immediately). What is persisted is the
operational state: plan versions, steps, a one-line decision summary, actions, evidence and
checkpoints - never private reasoning. COMPLETED requires the objective verifier to pass; a model
saying "done" is not evidence. Tool output is fed back as untrusted external content.

Alpha 2 (review A5, A7): the model sees a catalog built from the trusted, enabled manifests (id,
version, description, effect, input schema) and every decision is validated - including the tool
input against its schema - before anything reaches the broker. A run resumes from operational state:
the latest plan, persisted step observations, and the owner's answers and corrections; it never
replays private reasoning, and steps interrupted mid-flight are settled from the action ledger.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from jsonschema import Draft202012Validator

from runtime.memory.knowledge import KnowledgeContextService
from runtime.memory.manager import MemoryManager
from runtime.models.context import (
    Authority,
    ContextBuilder,
    ContextItem,
    ContextOverflow,
    RequiredContextWithheld,
)
from runtime.models.router import BudgetedModelClient, Requirements
from runtime.models.types import ModelRequest
from runtime.notifications import texts
from runtime.notifications.outbox import Notice, OutboxDispatcher
from runtime.tasks.engine import Lease, TaskEngine
from runtime.tasks.lease_keeper import DEFAULT_INTERVAL_S, LeaseKeeper, database_path
from runtime.tasks.limits import AttemptLimits, ProgressGuard, StepOutcome
from runtime.tasks.state_machine import TaskState
from runtime.tools.registry import RegistryError, ToolManifest
from runtime.verification.verifier import DeliverableSpec, Verifier
from security.broker.broker import Broker, DispatchResult
from security.egress.guard import EgressBlocked, highest, rank
from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "summary", "tool_id", "input_json", "artifact_id", "question", "capability_json"],
    "properties": {
        "decision": {"type": "string", "enum": ["tool", "finish", "ask_owner", "request_capability"]},
        "summary": {"type": "string", "maxLength": 300},
        "tool_id": {"type": "string"},
        "input_json": {"type": "string", "description": "JSON object with the tool input"},
        "artifact_id": {"type": "string", "description": "deliverable artifact id when finishing"},
        "question": {"type": "string"},
        "capability_json": {
            "type": "string",
            "description": "request_capability only: JSON with problem, missing_capability, provider, evidence, "
            "price {amount, currency, recurrence once|monthly|yearly, source}, data_shared [classes], "
            "alternatives [..], risk, test_plan",
        },
    },
}
CAPABILITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["problem", "missing_capability", "provider", "evidence", "price", "data_shared", "alternatives",
                 "risk", "test_plan"],
    "properties": {
        "problem": {"type": "string", "minLength": 5, "maxLength": 600},
        "missing_capability": {"type": "string", "minLength": 3, "maxLength": 300},
        "provider": {"type": "string", "minLength": 2, "maxLength": 200},
        "evidence": {"type": "string", "minLength": 5, "maxLength": 600},
        "price": {
            "type": "object",
            "additionalProperties": False,
            "required": ["amount", "currency", "recurrence", "source"],
            "properties": {
                "amount": {"type": "string", "pattern": "^[0-9]+([.,][0-9]{1,2})?$"},
                "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
                "recurrence": {"enum": ["once", "monthly", "yearly"]},
                "source": {"type": "string", "minLength": 3, "maxLength": 300},
            },
        },
        "data_shared": {"type": "array", "maxItems": 10,
                        "items": {"enum": ["PUBLIC", "INTERNAL", "PERSONAL", "SENSITIVE"]}},
        "alternatives": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 300}},
        "risk": {"type": "string", "minLength": 3, "maxLength": 400},
        "test_plan": {"type": "string", "minLength": 3, "maxLength": 400},
    },
}
_CAPABILITY_VALIDATOR = Draft202012Validator(CAPABILITY_SCHEMA)
_DECISION_VALIDATOR = Draft202012Validator(DECISION_SCHEMA)
MAX_OBSERVATION_CHARS = 40_000
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
POLICY_SUMMARY = (
    "Only the tools in the catalog are available, each with the exact input schema shown. External writes and purchases need task permission and may need "
    "owner approval; you cannot grant or assume approval. Finish only by naming the artifact_id of a "
    "deliverable you created; it will be verified objectively."
)


def parse_decision(text: str) -> dict[str, Any]:
    """Validate the COMPLETE decision contract before any field is read (A3-06, spec 4.1).

    Raises ``ValueError`` with a short, model-facing reason. Nothing downstream indexes or slices an
    unvalidated value, so a list, a missing field or a ``null`` summary cannot crash the worker.
    """
    try:
        decision: Any = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("the answer is not valid JSON") from None
    errors = sorted(_DECISION_VALIDATOR.iter_errors(decision), key=lambda e: list(e.absolute_path))
    if errors:
        where = "/".join(str(p) for p in errors[0].absolute_path) or "(root)"
        raise ValueError(f"the decision violates its schema at {where}: {errors[0].message[:160]}")
    assert isinstance(decision, dict)
    return decision


class Observation(NamedTuple):
    """Operational observation fed back to the model, with the classification of what it contains."""

    text: str
    ref: str
    authority: Authority
    classification: str = "INTERNAL"


@dataclass
class RunOutcome:
    task_id: str
    state: str
    reason: str
    steps: int = 0
    deliverable_id: str | None = None
    gaps: list[str] = field(default_factory=list)


class AgentRunner:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        *,
        broker: Broker,
        model: BudgetedModelClient,
        memory: MemoryManager,
        verifier: Verifier,
        tools: list[str],
        worker_id: str = "agent-1",
        max_steps: int = 200,  # absolute safety bound; lack of progress is limited by ProgressGuard (20)
        limits: AttemptLimits | None = None,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.broker = broker
        self.tasks: TaskEngine = broker.tasks
        self.model = model
        self.memory = memory
        self.verifier = verifier
        self.catalog = self._catalog(tools)
        self.tools = list(self.catalog)
        self.worker_id = worker_id
        self.max_steps = max_steps
        self.guard = ProgressGuard(self.tasks, limits)
        self.ctx_builder = ContextBuilder()
        self.actor = Actor("runtime", worker_id, "internal")
        self.keeper_interval_s = DEFAULT_INTERVAL_S
        self._last_verification: Any = None
        self.last_keeper_beats = 0

    # ------------------------------------------------------------------ tool catalog (3A)

    def _catalog(self, tool_ids: list[str]) -> dict[str, ToolManifest]:
        """Only enabled tools whose manifest resolves (hash-checked) are offered to the model."""
        catalog: dict[str, ToolManifest] = {}
        for tool_id in tool_ids:
            row = self.conn.execute(
                "SELECT version FROM tools WHERE tool_id = ? AND enabled = 1 ORDER BY registered_at DESC LIMIT 1",
                (tool_id,),
            ).fetchone()
            if row is None:
                continue
            try:
                manifest, _ = self.broker.registry.resolve(tool_id, row[0])
            except RegistryError:
                continue
            catalog[tool_id] = manifest
        return catalog

    def _catalog_text(self) -> str:
        entries = [
            {
                "tool_id": m.tool_id,
                "version": m.version,
                "description": m.description,
                "effect": m.effect_class,
                "input_schema": m.input_schema,
            }
            for m in self.catalog.values()
        ]
        return json.dumps(entries, ensure_ascii=False, sort_keys=True)

    def _validate(self, decision: dict[str, Any]) -> tuple[ToolManifest, dict[str, Any]] | str:
        """Validate the whole decision before the broker sees it. Returns a reason string when invalid."""
        if decision["decision"] == "finish":
            if not UUID_RE.match(str(decision.get("artifact_id", ""))):
                return "finish needs the artifact_id of a deliverable you created"
            return "ok-finish"
        if decision["decision"] == "ask_owner":
            return "ok-ask" if str(decision.get("question", "")).strip() else "ask_owner needs a question"
        if decision["decision"] == "request_capability":
            try:
                cap = json.loads(decision["capability_json"] or "null")
            except json.JSONDecodeError:
                return "capability_json is not valid JSON"
            errors = sorted(_CAPABILITY_VALIDATOR.iter_errors(cap), key=lambda e: list(e.absolute_path))
            if errors:
                where = "/".join(str(p) for p in errors[0].absolute_path) or "(root)"
                return f"capability request incomplete at {where}: {errors[0].message[:160]}"
            return "ok-capability"
        manifest = self.catalog.get(str(decision.get("tool_id", "")))
        if manifest is None:
            return f"tool '{decision.get('tool_id', '')}' is not in the catalog"
        try:
            tool_input = json.loads(decision.get("input_json") or "{}")
        except json.JSONDecodeError:
            return "input_json is not valid JSON"
        if not isinstance(tool_input, dict):
            return "input_json must be a JSON object"
        errors = sorted(Draft202012Validator(manifest.input_schema).iter_errors(tool_input), key=str)
        if errors:
            return f"input for {manifest.tool_id} violates its schema: " + "; ".join(
                e.message[:200] for e in errors[:3]
            )
        return manifest, tool_input

    # ------------------------------------------------------------------ resumption (3C)

    def _resume_state(self, task_id: str) -> tuple[str, list[Observation]]:
        """Latest plan + observations rebuilt from the database. A new plan only on the first run."""
        row = self.conn.execute(
            "SELECT id FROM plans WHERE task_id = ? ORDER BY version DESC LIMIT 1", (task_id,)
        ).fetchone()
        if row is None:
            return self._new_plan(task_id, "initial plan: iterate one verified step at a time"), []
        self._settle_interrupted_steps(task_id)
        observations: list[Observation] = [
            Observation(
                "This task was interrupted and is being resumed. Earlier completed steps are listed; do not "
                "repeat actions whose results are already known.",
                "system",
                Authority.VERIFIED_FACT,
            )
        ]
        for step in self.conn.execute(
            "SELECT s.description, s.status, o.content, o.trust, o.classification FROM steps s"
            " LEFT JOIN step_observations o"
            " ON o.step_id = s.id WHERE s.task_id = ? ORDER BY s.created_at, s.rowid",
            (task_id,),
        ).fetchall():
            observations.append(Observation(f"Earlier step ({step[1]}): {step[0]}", "system", Authority.VERIFIED_FACT))
            if step[2]:
                auth = Authority.EXTERNAL_CONTENT if step[3] == "untrusted" else Authority.VERIFIED_FACT
                observations.append(Observation(step[2], "step-observation", auth, step[4] or "INTERNAL"))
        observations += self._owner_messages(task_id)
        self._journal(
            task_id, "task.resumed", f"resumed on plan {row[0]} with {len(observations)} observation(s)"
        )
        return str(row[0]), observations

    def _owner_messages(self, task_id: str) -> list[Observation]:
        try:
            rows = self.conn.execute(
                "SELECT id, role, kind, content FROM messages WHERE task_id = ? AND kind IN"
                " ('question','answer') ORDER BY rowid",
                (task_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        out: list[Observation] = []
        for r in rows:
            if r[1] == "owner":
                out.append(Observation(f"Owner answer: {r[3]}", f"message:{r[0]}", Authority.OWNER_INSTRUCTION))
            else:
                out.append(Observation(f"You asked the owner: {r[3]}", f"message:{r[0]}", Authority.VERIFIED_FACT))
        return out

    def _settle_interrupted_steps(self, task_id: str) -> None:
        """A step left RUNNING by a crash is settled from the ledger; UNKNOWN effects stay unresolved."""
        for step in self.conn.execute(
            "SELECT id FROM steps WHERE task_id = ? AND status = 'RUNNING'", (task_id,)
        ).fetchall():
            actions = [
                r[0]
                for r in self.conn.execute(
                    "SELECT status FROM actions WHERE step_id = ?", (step[0],)
                ).fetchall()
            ]
            if "UNKNOWN" in actions or "DISPATCHING" in actions:
                continue  # reconciliation decides; never assume either outcome
            if "CONFIRMED" in actions:
                self._finish_step(step[0], "DONE")
                self._observe(
                    step[0],
                    task_id,
                    "The action of this step was confirmed before the interruption, but its output was not "
                    "captured. Read the relevant artifact again if you need its content.",
                    "verified",
                )
            else:
                self._finish_step(step[0], "FAILED")

    def _observe(
        self, step_id: str, task_id: str, content: str, trust: str, classification: str = "INTERNAL"
    ) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR REPLACE INTO step_observations(step_id, task_id, content, trust, created_at,"
                " classification) VALUES (?,?,?,?,?,?)",
                (step_id, task_id, content, trust, to_utc_str(self.clock.now()), classification),
            )

    def _deliver(self, task_id: str) -> None:
        """Best-effort immediate delivery; anything not delivered stays PENDING for the dispatcher."""
        try:
            OutboxDispatcher(self.conn, self.clock).deliver_pending(task_id)
        except Exception:  # noqa: S110 - the notice is durable in the outbox; the watchdog retries
            pass

    # ------------------------------------------------------------------ persistence helpers

    def _new_plan(self, task_id: str, reason: str) -> str:
        plan_id = new_id()
        with transaction(self.conn):
            v = self.conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM plans WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO plans(id, task_id, version, reason, created_at) VALUES (?,?,?,?,?)",
                (plan_id, task_id, int(v) + 1, reason[:500], to_utc_str(self.clock.now())),
            )
        return plan_id

    def _new_step(self, plan_id: str, task_id: str, description: str, expected: str) -> str:
        step_id = new_id()
        with transaction(self.conn):
            n = self.conn.execute(
                "SELECT COALESCE(MAX(ordinal), 0) FROM steps WHERE plan_id = ?", (plan_id,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO steps(id, plan_id, task_id, ordinal, description, expected_result, status, created_at)"
                " VALUES (?,?,?,?,?,?,'RUNNING',?)",
                (
                    step_id,
                    plan_id,
                    task_id,
                    int(n) + 1,
                    description[:500],
                    expected[:500],
                    to_utc_str(self.clock.now()),
                ),
            )
        return step_id

    def _finish_step(self, step_id: str, status: str) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE steps SET status = ? WHERE id = ?", (status, step_id))

    # ------------------------------------------------------------------ preparation

    def _prepare(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        for src, dst in (
            (TaskState.CREATED, TaskState.UNDERSTANDING),
            (TaskState.UNDERSTANDING, TaskState.PLANNING),
            (TaskState.PLANNING, TaskState.READY),
        ):
            if task["state"] == src:
                self.tasks.transition(
                    task_id,
                    dst,
                    expected_version=task["version"],
                    actor=self.actor,
                    reason="agent preparing task",
                )
                task = self.tasks.get(task_id)

    def _context(
        self, task: dict[str, Any], observations: list[Observation]
    ) -> list[ContextItem]:
        items = [ContextItem(Authority.POLICY, POLICY_SUMMARY, "policy", required=True)]
        versions = self.tasks.instructions(task["task_id"])
        for v in versions:  # the owner's words, oldest first; the last revision prevails (A3-03)
            label = "CURRENT (prevails over earlier instructions)" if v is versions[-1] else "superseded context"
            items.append(
                ContextItem(
                    Authority.OWNER_INSTRUCTION,
                    f"[revision {v['revision']} {v['kind']} - {label}]\n{v['instruction']}",
                    f"task:{task['task_id']}:rev{v['revision']}",
                    required=v is versions[-1] or v["kind"] == "ORIGINAL",
                )
            )
        items += [
            ContextItem(
                Authority.TASK_OBJECTIVE,
                "Deliverable criteria: "
                + "; ".join(c["description"] for c in task["completion_criteria"])
                + "\nTool catalog (JSON): "
                + self._catalog_text()
                + "\nAttached artifacts: "
                + ", ".join(self._attached(task["task_id"])),
                "criteria",
                required=True,
            ),
        ]
        query = " ".join(v["instruction"] for v in versions[-2:])
        for k in KnowledgeContextService(self.conn, self.clock).context_for(task["employee_id"], query):
            items.append(  # the same knowledge path as the conversation (A3-01)
                ContextItem(Authority.OWNER_MEMORY, k.render(), f"memory:{k.hit.memory_id}", k.hit.sensitivity)
            )
        for obs in observations[-12:]:
            items.append(ContextItem(obs.authority, obs.text, obs.ref, obs.classification))
        return items

    def _attached(self, task_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT a.id, a.name FROM artifact_links l JOIN artifacts a ON a.id = l.artifact_id"
            " WHERE l.task_id = ? AND l.relation = 'input'",
            (task_id,),
        ).fetchall()
        return [f"{r[1]} (artifact_id {r[0]})" for r in rows]

    def _decide(self, task: dict[str, Any], observations: list[Observation]) -> dict[str, Any]:
        items = self._context(task, observations)
        ceiling = self._egress_ceiling()
        built = self.ctx_builder.build(items, max_classification=ceiling)
        if any(not ref.startswith("memory:") for ref in built.withheld):
            # Work content (a document, a tool result) may not be disclosed: never decide without it.
            raise RequiredContextWithheld(built.withheld, "SENSITIVE")
        classification = highest(task["data_policy"], built.classification)
        resp = self.model.call(
            task_id=task["task_id"],
            # repairing a failed verification is hard work (automatic mode prefers the strongest profile)
            req=Requirements(
                structured_output=True,
                data_classification=classification,
                complexity="hard" if self._last_verification is not None else "normal",
            ),
            request=ModelRequest(
                "auto",
                built.messages,
                max_output_tokens=4000,
                json_schema=DECISION_SCHEMA,
                classification=classification,
            ),
        )
        return parse_decision(resp.output_text)

    def _egress_ceiling(self) -> str | None:
        guard = getattr(self.model, "egress", None)
        if guard is None:
            return None
        providers = {e.provider for e in self.model.router.catalog}
        return min((guard.max_allowed(p, "task") for p in providers), key=rank, default="PERSONAL")

    # ------------------------------------------------------------------ run

    def run(self, task_id: str, spec: DeliverableSpec) -> RunOutcome:
        self._prepare(task_id)
        lease = self.tasks.acquire_lease(task_id, self.worker_id)
        path = database_path(self.conn)
        if path is None:  # in-memory database: no second connection can renew the lease
            try:
                return self._run_leased(task_id, spec, lease)
            finally:
                self._deliver(task_id)
        keeper = LeaseKeeper(
            path, self.clock, lease, lease_ttl=self.tasks.lease_ttl, interval_s=self.keeper_interval_s
        )
        with keeper:  # renews while model calls and dispatches block this thread (A3-05)
            try:
                return self._run_leased(task_id, spec, lease)
            finally:
                self.last_keeper_beats = keeper.beats
                self._deliver(task_id)

    def _run_leased(self, task_id: str, spec: DeliverableSpec, lease: Lease) -> RunOutcome:
        plan_id, observations = self._resume_state(task_id)
        seen_revision = int(self.tasks.get(task_id)["instruction_revision"])
        steps = 0
        gaps: list[str] = []
        while steps < self.max_steps:
            steps += 1
            try:
                lease = self.tasks.heartbeat(lease)  # stop/pause/cancel end the run here
            except AtlasError:
                return self._outcome(task_id, "lease revoked (paused, stopped or cancelled)", steps)
            task = self.tasks.get(task_id)
            if task["instruction_revision"] != seen_revision:  # checked before every inference (A3-03)
                seen_revision = int(task["instruction_revision"])
                plan_id = self._new_plan(task_id, f"re-plan after owner instruction revision {seen_revision}")
                observations.append(
                    Observation(
                        f"The owner changed the instructions (now revision {seen_revision}, shown as CURRENT). "
                        "Re-plan the remaining work; keep results already obtained, do not repeat them.",
                        "system",
                        Authority.VERIFIED_FACT,
                    )
                )
            try:
                decision = self._decide(task, observations)
            except (RequiredContextWithheld, EgressBlocked) as exc:  # A3-02: ask, never leak or guess
                self._safe_release(
                    lease,
                    TaskState.WAITING_USER,
                    exc.message,
                    notice=(
                        "question",
                        "Para continuar preciso enviar ao provedor de IA conteúdo classificado como sensível "
                        "desta tarefa. Sem a sua autorização eu não envio. Você pode autorizar esse uso em "
                        "Configurações › Privacidade (só para tarefas), retirar o trecho sensível ou pedir que "
                        "eu entregue o que for possível sem ele. Nada foi enviado.",
                        None,
                    ),
                )
                return self._outcome(task_id, exc.message, steps)
            except ContextOverflow as exc:  # never drop the request silently: ask the owner (A3-18)
                self._safe_release(
                    lease,
                    TaskState.WAITING_USER,
                    exc.message,
                    notice=(
                        "question",
                        "O pedido e as instruções em vigor desta tarefa não cabem de uma vez no contexto do "
                        "modelo. Qual parte devo fazer primeiro? Nada foi enviado ao modelo.",
                        None,
                    ),
                )
                return self._outcome(task_id, exc.message, steps)
            except (AtlasError, ValueError) as exc:
                reason = exc.message if isinstance(exc, AtlasError) else f"invalid decision: {exc}"
                if isinstance(exc, AtlasError) and exc.code in (
                    ErrorCode.BUDGET_EXCEEDED,
                    ErrorCode.UNAUTHORIZED,
                    ErrorCode.POLICY_DENIED,
                ):
                    budget = exc.code == ErrorCode.BUDGET_EXCEEDED
                    self._safe_release(
                        lease,
                        TaskState.BLOCKED if budget else TaskState.WAITING_USER,
                        reason,
                        "BUDGET_EXCEEDED" if budget else None,
                        (
                            "status",
                            texts.BUDGET_EXHAUSTED
                            if budget
                            else f"Não consegui usar a inteligência ({reason}). A tarefa aguarda você.",
                            None,
                        ),
                    )
                    return self._outcome(task_id, reason, steps)
                state = self.guard.record(lease, StepOutcome.NO_NEW_RESULT)
                observations.append(
                    Observation(f"Your previous answer was rejected: {reason}", "system", Authority.VERIFIED_FACT)
                )
                if state != TaskState.RUNNING:
                    return self._outcome(task_id, reason, steps)
                continue
            self.tasks.checkpoint(
                task_id,
                {
                    "step": steps,
                    "decision": decision["decision"],
                    "summary": decision["summary"],
                },
            )
            verdict = self._validate(decision)
            if isinstance(verdict, str) and not verdict.startswith("ok-"):
                observations.append(
                    Observation(
                        f"Your decision was rejected before execution: {verdict}",
                        "system",
                        Authority.VERIFIED_FACT,
                    )
                )
                state = self.guard.record(lease, StepOutcome.NO_NEW_RESULT)
                if state != TaskState.RUNNING:
                    return self._outcome(task_id, verdict, steps)
                continue
            if decision["decision"] == "ask_owner":
                question = decision["question"][:900]
                self._journal(task_id, "task.question", question)
                self._safe_release(
                    lease, TaskState.WAITING_USER, "agent asked the owner a question", notice=("question", question, None)
                )
                return self._outcome(task_id, "waiting for the owner", steps)
            if decision["decision"] == "request_capability":  # N18: concrete request, owner decides
                from runtime.capabilities.requests import CapabilityRequests

                CapabilityRequests(self.conn, self.clock).file(
                    task_id=task_id,
                    worker=Actor("worker", lease.worker_id, "internal"),
                    request=json.loads(decision["capability_json"]),
                )
                return self._outcome(task_id, "waiting for the owner's decision on a capability request", steps)
            if decision["decision"] == "finish":
                result = self.verifier.verify_text_artifact(task_id, decision.get("artifact_id", ""), spec)
                self._last_verification = result
                if result.passed:
                    return self._complete(task_id, lease, result.evidence_id, decision["artifact_id"], steps)
                gaps = result.gaps
                observations.append(
                    Observation(
                        "Verification failed, the task is NOT complete. Gaps: " + "; ".join(gaps),
                        "verifier",
                        Authority.VERIFIED_FACT,
                    )
                )
                state = self.guard.record(
                    lease,
                    StepOutcome.REPLANNED_WITHOUT_PROGRESS,
                    notice=(
                        "status",
                        "Não concluí: a entrega não passou na verificação. Faltou: "
                        + "; ".join(gaps)[:1500]
                        + ". O arquivo parcial continua disponível; diga se devo continuar ou aceitar assim.",
                        decision["artifact_id"] if result.checks.get("belongs_to_task") else None,
                    ),
                )
                if state != TaskState.RUNNING:
                    return self._outcome(task_id, "verification kept failing", steps, gaps=gaps)
                plan_id = self._new_plan(
                    task_id, "repair after failed verification: " + "; ".join(gaps)[:400]
                )
                continue
            # decision == tool, already validated against the catalog
            assert not isinstance(verdict, str)
            outcome = self._run_tool(
                task_id, plan_id, lease, decision, verdict, observations, int(task["instruction_revision"])
            )
            if outcome is not None:  # the broker already queued its notice with the state change
                return self._outcome(task_id, outcome, steps)
        self._safe_release(
            lease, TaskState.BLOCKED, "step budget exhausted", "NO_PROGRESS", ("status", texts.NO_PROGRESS, None)
        )
        return self._outcome(task_id, "step budget exhausted", steps, gaps=gaps)

    def _run_tool(
        self,
        task_id: str,
        plan_id: str,
        lease: Lease,
        decision: dict[str, Any],
        validated: tuple[ToolManifest, dict[str, Any]],
        observations: list[Observation],
        instruction_revision: int,
    ) -> str | None:
        manifest, tool_input = validated
        tool_id = manifest.tool_id
        step_id = self._new_step(plan_id, task_id, decision.get("summary") or tool_id, f"result of {tool_id}")
        proposal = {
            "schema_version": "1.0",
            "task_id": task_id,
            "step_id": step_id,
            "tool_id": tool_id,
            "tool_version": manifest.version,
            "input": tool_input,
            "expected_outcome": decision.get("summary") or tool_id,
            "verification": {"kind": "deterministic_check", "required": True},
            "instruction_revision": instruction_revision,
        }
        try:
            res: DispatchResult = self.broker.submit(proposal, lease)
        except AtlasError as exc:
            self._finish_step(step_id, "FAILED")
            if exc.code == ErrorCode.UNAUTHORIZED:
                return "lease revoked (paused, stopped or cancelled)"
            if exc.code == ErrorCode.VERSION_CONFLICT:  # a correction arrived: not a lack of progress
                observations.append(Observation(f"Proposal discarded: {exc.message}", "broker", Authority.VERIFIED_FACT))
                return None
            observations.append(Observation(f"Proposal refused: {exc.message}", "broker", Authority.VERIFIED_FACT))
            state = self.guard.record(lease, StepOutcome.NO_NEW_RESULT)
            return None if state == TaskState.RUNNING else "no progress"
        if res.status == "CONFIRMED":
            text = json.dumps(res.output, ensure_ascii=False) if res.output is not None else f"{tool_id} confirmed"
            if len(text) > MAX_OBSERVATION_CHARS:  # never cut JSON in the middle (A3-10)
                text = json.dumps(
                    {
                        "note": "output too large for one observation; nothing was cut - read it in pages "
                        "with documents.read (cursor) or narrow it with documents.search",
                        "tool": tool_id,
                        "keys": sorted(res.output or {})[:20],
                    }
                )
            cls = str((res.output or {}).get("classification") or "INTERNAL")  # set by the trusted adapter
            self._observe(step_id, task_id, text, "untrusted", cls)  # persisted before the step is marked done
            self._finish_step(step_id, "DONE")
            observations.append(Observation(text, f"tool:{tool_id}", Authority.EXTERNAL_CONTENT, cls))
            # Progress = a new deliverable version, or new document segments read (a long document read
            # page by page is progress, not a loop).
            wrote = tool_id in ("artifact.write_text", "artifact.write_document")
            read_more = tool_id in ("artifact.read_text", "documents.read") and bool((res.output or {}).get("segments"))
            self.guard.record(lease, StepOutcome.VERIFIED_RESULT if wrote or read_more else StepOutcome.NO_NEW_RESULT)
            return None
        self._finish_step(step_id, "FAILED")
        if res.status in ("APPROVAL_REQUIRED", "UNKNOWN", "BUDGET_EXCEEDED"):
            return {
                "APPROVAL_REQUIRED": "waiting for owner approval",
                "UNKNOWN": "external effect unknown",
                "BUDGET_EXCEEDED": "budget exhausted",
            }[res.status]
        observations.append(Observation(f"Action {res.status}: {res.reason}", "broker", Authority.VERIFIED_FACT))
        state = self.guard.record(
            lease,
            StepOutcome.TRANSIENT_FAILURE
            if res.status == "FAILED"
            else StepOutcome.REPLANNED_WITHOUT_PROGRESS,
        )
        return None if state == TaskState.RUNNING else f"stopped after {res.status}"

    def _complete(
        self, task_id: str, lease: Lease, evidence_id: str | None, artifact_id: str, steps: int
    ) -> RunOutcome:
        assert evidence_id is not None
        per = self._last_verification.criteria if self._last_verification else {}
        for c in self.tasks.get(task_id)["completion_criteria"]:
            own = per.get(c["criterion_id"])
            if own is not None and own.passed and own.evidence_id:  # its OWN evidence (A3-07)
                self.tasks.satisfy_criterion(task_id, c["criterion_id"], own.evidence_id)
        self.tasks.release(lease, TaskState.VERIFYING, "deliverable verified")
        name = self.conn.execute("SELECT name FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        self.tasks.complete(
            task_id,
            actor=self.actor,
            expected_version=self.tasks.get(task_id)["version"],
            notice=("result", f"Concluí a tarefa. Entrega verificada: {name[0] if name else artifact_id}.", artifact_id),
        )
        self._journal(task_id, "task.delivered", f"deliverable artifact {artifact_id} verified")
        out = self._outcome(task_id, "completed with verified deliverable", steps)
        out.deliverable_id = artifact_id
        return out

    def _safe_release(
        self,
        lease: Lease,
        to: TaskState,
        reason: str,
        blocked: str | None = None,
        notice: Notice | None = None,
    ) -> None:
        try:
            self.tasks.release(lease, to, reason, blocked_reason=blocked, notice=notice)
        except AtlasError:
            pass  # lease already revoked by the owner; nothing to release

    def _journal(self, task_id: str, type_: str, summary: str) -> None:
        emp = self.conn.execute("SELECT employee_id FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
        with transaction(self.conn):
            journal.append(
                self.conn,
                self.clock,
                employee_id=emp,
                task_id=task_id,
                type=type_,
                actor=self.actor,
                summary=summary,
            )

    def _outcome(self, task_id: str, reason: str, steps: int, gaps: list[str] | None = None) -> RunOutcome:
        return RunOutcome(task_id, self.tasks.get(task_id)["state"], reason, steps, gaps=gaps or [])
