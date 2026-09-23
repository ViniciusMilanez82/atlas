"""Agent loop - planner/executor/verifier cycle (spec 6.2, 9, 15; AT-016, review Etapa 3).

objective -> constraints -> relevant memories -> persisted plan -> ONE proposed step -> broker ->
observed result -> verification -> bounded replanning -> delivery.

The model only proposes the next decision as strict JSON. Tools run exclusively through the broker
with this worker's lease (so pause/stop/cancel revoke it immediately). What is persisted is the
operational state: plan versions, steps, a one-line decision summary, actions, evidence and
checkpoints - never private reasoning. COMPLETED requires the objective verifier to pass; a model
saying "done" is not evidence. Tool output is fed back as untrusted external content.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from runtime.memory.manager import MemoryManager
from runtime.models.context import Authority, ContextBuilder, ContextItem
from runtime.models.router import BudgetedModelClient, Requirements
from runtime.models.types import ModelRequest
from runtime.tasks.engine import Lease, TaskEngine
from runtime.tasks.limits import AttemptLimits, ProgressGuard, StepOutcome
from runtime.tasks.state_machine import TaskState
from runtime.verification.verifier import DeliverableSpec, Verifier
from security.broker.broker import Broker, DispatchResult
from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "summary", "tool_id", "input_json", "artifact_id", "question"],
    "properties": {
        "decision": {"type": "string", "enum": ["tool", "finish", "ask_owner"]},
        "summary": {"type": "string", "maxLength": 300},
        "tool_id": {"type": "string"},
        "input_json": {"type": "string", "description": "JSON object with the tool input"},
        "artifact_id": {"type": "string", "description": "deliverable artifact id when finishing"},
        "question": {"type": "string"},
    },
}
POLICY_SUMMARY = (
    "Only the tools listed are available. External writes and purchases need task permission and may need "
    "owner approval; you cannot grant or assume approval. Finish only by naming the artifact_id of a "
    "deliverable you created; it will be verified objectively."
)


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
        max_steps: int = 20,
        limits: AttemptLimits | None = None,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.broker = broker
        self.tasks: TaskEngine = broker.tasks
        self.model = model
        self.memory = memory
        self.verifier = verifier
        self.tools = tools
        self.worker_id = worker_id
        self.max_steps = max_steps
        self.guard = ProgressGuard(self.tasks, limits)
        self.ctx_builder = ContextBuilder()
        self.actor = Actor("runtime", worker_id, "internal")

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
        self, task: dict[str, Any], observations: list[tuple[str, str, Authority]]
    ) -> list[ContextItem]:
        items = [
            ContextItem(Authority.POLICY, POLICY_SUMMARY, "policy"),
            ContextItem(Authority.OWNER_INSTRUCTION, task["objective"], f"task:{task['task_id']}"),
            ContextItem(
                Authority.TASK_OBJECTIVE,
                "Deliverable criteria: "
                + "; ".join(c["description"] for c in task["completion_criteria"])
                + "\nAvailable tools: "
                + ", ".join(self.tools)
                + "\nAttached artifacts: "
                + ", ".join(self._attached(task["task_id"])),
                "criteria",
            ),
        ]
        try:
            for hit in self.memory.search(
                employee_id=task["employee_id"], query=task["objective"], limit=5, match_any=True
            ):
                items.append(ContextItem(Authority.VERIFIED_FACT, hit.content, f"memory:{hit.memory_id}"))
        except AtlasError:
            pass
        for text, ref, auth in observations[-12:]:
            items.append(ContextItem(auth, text, ref))
        return items

    def _attached(self, task_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT a.id, a.name FROM artifact_links l JOIN artifacts a ON a.id = l.artifact_id"
            " WHERE l.task_id = ? AND l.relation = 'input'",
            (task_id,),
        ).fetchall()
        return [f"{r[1]} (artifact_id {r[0]})" for r in rows]

    def _decide(self, task: dict[str, Any], observations: list[tuple[str, str, Authority]]) -> dict[str, Any]:
        built = self.ctx_builder.build(self._context(task, observations))
        resp = self.model.call(
            task_id=task["task_id"],
            req=Requirements(structured_output=True, data_classification=task["data_policy"]),
            request=ModelRequest("auto", built.messages, max_output_tokens=4000, json_schema=DECISION_SCHEMA),
        )
        decision: dict[str, Any] = json.loads(resp.output_text)
        if decision.get("decision") not in ("tool", "finish", "ask_owner"):
            raise ValueError("invalid decision")
        return decision

    # ------------------------------------------------------------------ run

    def run(self, task_id: str, spec: DeliverableSpec) -> RunOutcome:
        self._prepare(task_id)
        lease = self.tasks.acquire_lease(task_id, self.worker_id)
        plan_id = self._new_plan(task_id, "initial plan: iterate one verified step at a time")
        observations: list[tuple[str, str, Authority]] = []
        steps = 0
        gaps: list[str] = []
        while steps < self.max_steps:
            steps += 1
            try:
                lease = self.tasks.heartbeat(lease)  # stop/pause/cancel end the run here
            except AtlasError:
                return self._outcome(task_id, "lease revoked (paused, stopped or cancelled)", steps)
            task = self.tasks.get(task_id)
            try:
                decision = self._decide(task, observations)
            except (AtlasError, ValueError, json.JSONDecodeError) as exc:
                reason = exc.message if isinstance(exc, AtlasError) else "model returned an invalid decision"
                if isinstance(exc, AtlasError) and exc.code in (
                    ErrorCode.BUDGET_EXCEEDED,
                    ErrorCode.UNAUTHORIZED,
                    ErrorCode.POLICY_DENIED,
                ):
                    self._safe_release(
                        lease,
                        TaskState.BLOCKED
                        if exc.code == ErrorCode.BUDGET_EXCEEDED
                        else TaskState.WAITING_USER,
                        reason,
                        "BUDGET_EXCEEDED" if exc.code == ErrorCode.BUDGET_EXCEEDED else None,
                    )
                    return self._outcome(task_id, reason, steps)
                state = self.guard.record(lease, StepOutcome.NO_NEW_RESULT)
                observations.append(
                    (f"Your previous answer was rejected: {reason}", "system", Authority.VERIFIED_FACT)
                )
                if state != TaskState.RUNNING:
                    return self._outcome(task_id, reason, steps)
                continue
            self.tasks.checkpoint(
                task_id,
                {
                    "step": steps,
                    "decision": decision["decision"],
                    "summary": decision.get("summary", "")[:300],
                },
            )
            if decision["decision"] == "ask_owner":
                self._journal(task_id, "task.question", decision.get("question", "")[:900])
                self._safe_release(lease, TaskState.WAITING_USER, "agent asked the owner a question")
                return self._outcome(task_id, "waiting for the owner", steps)
            if decision["decision"] == "finish":
                result = self.verifier.verify_text_artifact(task_id, decision.get("artifact_id", ""), spec)
                if result.passed:
                    return self._complete(task_id, lease, result.evidence_id, decision["artifact_id"], steps)
                gaps = result.gaps
                observations.append(
                    (
                        "Verification failed, the task is NOT complete. Gaps: " + "; ".join(gaps),
                        "verifier",
                        Authority.VERIFIED_FACT,
                    )
                )
                state = self.guard.record(lease, StepOutcome.REPLANNED_WITHOUT_PROGRESS)
                if state != TaskState.RUNNING:
                    return self._outcome(task_id, "verification kept failing", steps, gaps=gaps)
                plan_id = self._new_plan(
                    task_id, "repair after failed verification: " + "; ".join(gaps)[:400]
                )
                continue
            # decision == tool
            outcome = self._run_tool(task_id, plan_id, lease, decision, observations)
            if outcome is not None:
                return self._outcome(task_id, outcome, steps)
        self._safe_release(lease, TaskState.BLOCKED, "step budget exhausted", "NO_PROGRESS")
        return self._outcome(task_id, "step budget exhausted", steps, gaps=gaps)

    def _run_tool(
        self,
        task_id: str,
        plan_id: str,
        lease: Lease,
        decision: dict[str, Any],
        observations: list[tuple[str, str, Authority]],
    ) -> str | None:
        tool_id = str(decision.get("tool_id", ""))
        try:
            tool_input = json.loads(decision.get("input_json") or "{}")
        except json.JSONDecodeError:
            tool_input = None
        step_id = self._new_step(plan_id, task_id, decision.get("summary", tool_id), f"result of {tool_id}")
        if tool_id not in self.tools or not isinstance(tool_input, dict):
            self._finish_step(step_id, "FAILED")
            observations.append(
                (
                    f"Tool '{tool_id}' is not available or its input is not an object.",
                    "system",
                    Authority.VERIFIED_FACT,
                )
            )
            state = self.guard.record(lease, StepOutcome.NO_NEW_RESULT)
            return None if state == TaskState.RUNNING else "no progress"
        proposal = {
            "schema_version": "1.0",
            "task_id": task_id,
            "step_id": step_id,
            "tool_id": tool_id,
            "tool_version": "1.0.0",
            "input": tool_input,
            "expected_outcome": decision.get("summary") or tool_id,
            "verification": {"kind": "deterministic_check", "required": True},
        }
        try:
            res: DispatchResult = self.broker.submit(proposal, lease)
        except AtlasError as exc:
            self._finish_step(step_id, "FAILED")
            if exc.code == ErrorCode.UNAUTHORIZED:
                return "lease revoked (paused, stopped or cancelled)"
            observations.append((f"Proposal refused: {exc.message}", "broker", Authority.VERIFIED_FACT))
            state = self.guard.record(lease, StepOutcome.NO_NEW_RESULT)
            return None if state == TaskState.RUNNING else "no progress"
        if res.status == "CONFIRMED":
            self._finish_step(step_id, "DONE")
            if res.output is not None:
                observations.append(
                    (
                        json.dumps(res.output, ensure_ascii=False)[:20_000],
                        f"tool:{tool_id}",
                        Authority.EXTERNAL_CONTENT,
                    )
                )
            wrote = tool_id == "artifact.write_text"
            self.guard.record(lease, StepOutcome.VERIFIED_RESULT if wrote else StepOutcome.NO_NEW_RESULT)
            return None
        self._finish_step(step_id, "FAILED")
        if res.status in ("APPROVAL_REQUIRED", "UNKNOWN", "BUDGET_EXCEEDED"):
            return {
                "APPROVAL_REQUIRED": "waiting for owner approval",
                "UNKNOWN": "external effect unknown",
                "BUDGET_EXCEEDED": "budget exhausted",
            }[res.status]
        observations.append((f"Action {res.status}: {res.reason}", "broker", Authority.VERIFIED_FACT))
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
        for c in self.tasks.get(task_id)["completion_criteria"]:
            if c["required"]:
                self.tasks.satisfy_criterion(task_id, c["criterion_id"], evidence_id)
        self.tasks.release(lease, TaskState.VERIFYING, "deliverable verified")
        self.tasks.complete(task_id, actor=self.actor, expected_version=self.tasks.get(task_id)["version"])
        self._journal(task_id, "task.delivered", f"deliverable artifact {artifact_id} verified")
        out = self._outcome(task_id, "completed with verified deliverable", steps)
        out.deliverable_id = artifact_id
        return out

    def _safe_release(self, lease: Lease, to: TaskState, reason: str, blocked: str | None = None) -> None:
        try:
            self.tasks.release(lease, to, reason, blocked_reason=blocked)
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
