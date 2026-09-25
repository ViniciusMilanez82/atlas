"""Task Engine (spec 9, 12.3, 12.4; AT-010.1..010.4).

Persistent task lifecycle with optimistic versions, leases with fencing tokens, pause, resume,
cancel, "stop everything" and restart recovery. Leaving RUNNING always bumps the fencing token,
so a worker that lost its lease can never dispatch again (the broker re-checks the token inside
the dispatch transaction).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from runtime.notifications.outbox import Notice, enqueue_in_txn
from runtime.tasks.state_machine import TERMINAL, TaskState, check_transition
from runtime.verification.conditions import extract_conditions, fold
from runtime.verification.criteria import CHECKED_CONDITIONS, key_terms
from security.egress.guard import highest
from security.egress.lineage import classify_text, instruction_classification
from shared.actors import SYSTEM, Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.contracts import validate
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.money import Money
from storage import journal
from storage.db import require_transaction, transaction

DEFAULT_LEASE_TTL = timedelta(seconds=60)
# A correction that replaces the subject (not only adds to it) supersedes the earlier coverage (R5-04).
_REPLACES = re.compile(
    r"\b(abandone|esqueca|em vez de|ao inves de|substitua|troque|mude para|somente sobre|apenas sobre|"
    r"nao quero mais|deixe de lado)\b"
)
_CORRECTION_WORDS = {"verda", "corri", "corre", "mudei", "ideia", "aband", "somen", "apena", "agora", "tambe"}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
_FORBIDDEN_CHECKPOINT_KEYS = {"reasoning", "chain_of_thought", "thoughts", "scratchpad"}


@dataclass(frozen=True)
class Lease:
    task_id: str
    worker_id: str
    fencing_token: int
    expires_at: str


@dataclass
class StopReport:
    paused_tasks: list[str] = field(default_factory=list)
    in_flight_actions: list[str] = field(default_factory=list)
    unknown_actions: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    control_epoch: int = 0


@dataclass
class CancelReport:
    task_id: str
    cancelled_actions: list[str] = field(default_factory=list)
    revoked_approvals: list[str] = field(default_factory=list)
    effects_already_happened: list[str] = field(default_factory=list)
    effects_uncertain: list[str] = field(default_factory=list)


@dataclass
class RecoveryReport:
    released_leases: list[str] = field(default_factory=list)
    actions_marked_unknown: list[str] = field(default_factory=list)
    tasks_blocked: list[str] = field(default_factory=list)
    tasks_ready: list[str] = field(default_factory=list)
    approvals_expired: list[str] = field(default_factory=list)


def _err(code: ErrorCode, msg: str, **kw: Any) -> AtlasError:
    return AtlasError(code, msg, **kw)


class TaskEngine:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, lease_ttl: timedelta = DEFAULT_LEASE_TTL):
        self.conn = conn
        self.clock = clock
        self.lease_ttl = lease_ttl

    # ------------------------------------------------------------------ creation and reads

    def create(
        self,
        actor: Actor,
        *,
        employee_id: str,
        objective: str,
        external_writes: bool = False,
        purchases: bool = False,
        criteria: list[tuple[Any, ...]] | None = None,
        priority: str = "NORMAL",
        data_policy: str = "INTERNAL",
        budget_limit: Money | None = None,
        deadline: str | None = None,
        parent_task_id: str | None = None,
        conversation_id: str | None = None,
        client_request_id: str | None = None,
        original_request: str | None = None,
        source_message_id: str | None = None,
        input_artifact_ids: list[str] | None = None,
        control_epoch: int | None = None,
    ) -> str:
        """Persist a task before anything claims work has started (spec 3.3).

        ``original_request`` is the owner's full text (the objective may be a shorter statement); it is
        stored verbatim as instruction revision 1 so later summaries never replace it (spec 13.1).

        Publication is atomic (A3-12, spec 5.2): the task row, criteria, instruction, input attachments and
        the link to the source message commit together, so a worker can never pick up a task whose input
        package is incomplete. Every attachment must belong to the employee or nothing is created.

        ``client_request_id`` makes creation idempotent: resending the same request (after a lost reply or
        a reconnect) returns the task that already exists instead of creating a duplicate.

        ``control_epoch`` is the stop-all epoch in force when the owner's request was RECEIVED (R5-03). If
        the owner stopped everything since, the task is still published (nothing is lost) but PAUSED:
        only an explicit resume makes it executable. A subtask inherits its parent's epoch.
        """
        if actor.kind == "owner":
            owner_id = actor.id
        elif actor.kind == "runtime" and parent_task_id:
            parent = self._row(parent_task_id)
            owner_id = parent["owner_id"]
        else:
            raise _err(
                ErrorCode.UNAUTHORIZED, "tasks are created by the owner, or as subtasks by the runtime"
            )
        emp = self.conn.execute("SELECT owner_id FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if emp is None or emp["owner_id"] != owner_id:
            raise _err(ErrorCode.UNAUTHORIZED, "employee does not belong to this owner")
        if client_request_id is not None:
            existing = self.conn.execute(
                "SELECT id FROM tasks WHERE employee_id = ? AND client_request_id = ?",
                (employee_id, client_request_id),
            ).fetchone()
            if existing:
                return str(existing[0])
        task_id = new_id()
        now = to_utc_str(self.clock.now())
        request_text = (original_request or objective)[:32000]
        with transaction(self.conn):
            current_epoch = self._epoch(employee_id)
            if parent_task_id is not None and control_epoch is None:
                control_epoch = int(self._row(parent_task_id)["control_epoch"])
            epoch = current_epoch if control_epoch is None else control_epoch
            stale = epoch < current_epoch
            # R5-01: the task is at least as protected as the owner's words it was created from.
            instruction_class = highest(
                self._message_class(source_message_id), classify_text(request_text), classify_text(objective)
            )
            data_policy = highest(data_policy, instruction_class)
            self.conn.execute(
                "INSERT INTO tasks(id, owner_id, employee_id, objective, constraints_json, priority, data_policy,"
                " budget_amount_minor, budget_currency, state, parent_task_id, deadline, created_at, updated_at,"
                " conversation_id, client_request_id, control_epoch, paused_from)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    owner_id,
                    employee_id,
                    objective,
                    json.dumps({"external_writes": external_writes, "purchases": purchases}),
                    priority,
                    data_policy,
                    budget_limit.amount_minor if budget_limit else None,
                    budget_limit.currency if budget_limit else None,
                    TaskState.PAUSED if stale else TaskState.CREATED,
                    parent_task_id,
                    deadline,
                    now,
                    now,
                    conversation_id,
                    client_request_id,
                    epoch,
                    TaskState.CREATED if stale else None,
                ),
            )
            for c in criteria or []:  # (description, required[, check_kind, params]) - A3-07
                self.conn.execute(
                    "INSERT INTO task_criteria(id, task_id, description, required, check_kind, params_json)"
                    " VALUES (?,?,?,?,?,?)",
                    (
                        new_id(),
                        task_id,
                        c[0],
                        int(c[1]),
                        c[2] if len(c) > 2 else None,
                        json.dumps(c[3]) if len(c) > 3 and c[3] else None,
                    ),
                )
            for aid in dict.fromkeys(input_artifact_ids or []):
                art = self.conn.execute("SELECT employee_id FROM artifacts WHERE id = ?", (aid,)).fetchone()
                if art is None or art["employee_id"] != employee_id:
                    raise _err(ErrorCode.INVALID_INPUT, "attachment not found for this employee")
                self.conn.execute(
                    "INSERT OR IGNORE INTO artifact_links(artifact_id, task_id, relation) VALUES (?,?,'input')",
                    (aid, task_id),
                )
            if source_message_id is not None:
                self.conn.execute(
                    "UPDATE messages SET task_id = ? WHERE id = ? AND task_id IS NULL", (task_id, source_message_id)
                )
            self.conn.execute(
                "INSERT INTO task_instruction_versions(task_id, revision, kind, instruction, material, author,"
                " source_message_id, created_at, classification, content_sha256) VALUES (?,1,'ORIGINAL',?,1,?,?,?,?,?)",
                (task_id, request_text, f"{actor.kind}:{actor.id}", source_message_id, now,
                 highest(data_policy, instruction_class), sha256_text(request_text)),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=employee_id,
                task_id=task_id,
                type="task.created",
                actor=actor,
                summary=f"task created (priority {priority})"
                + (
                    f"; published PAUSED: requested before stop-all (epoch {epoch} < {current_epoch})"
                    if stale
                    else ""
                ),
            )
        validate("task", self.get(task_id))
        return task_id

    def _epoch(self, employee_id: str) -> int:
        row = self.conn.execute("SELECT control_epoch FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return int(row[0]) if row else 0

    def _message_class(self, message_id: str | None) -> str:
        if message_id is None:
            return "INTERNAL"
        row = self.conn.execute("SELECT classification FROM messages WHERE id = ?", (message_id,)).fetchone()
        return str(row[0]) if row else "SENSITIVE"  # an unknown origin is never treated as harmless

    def _row(self, task_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise _err(ErrorCode.INVALID_INPUT, "unknown task")
        return row  # type: ignore[no-any-return]

    def get(self, task_id: str) -> dict[str, Any]:
        r = self._row(task_id)
        criteria = self.conn.execute(
            "SELECT id, description, required FROM task_criteria WHERE task_id = ? AND superseded_revision IS NULL"
            " ORDER BY rowid",
            (task_id,),
        ).fetchall()
        return {
            "schema_version": "1.0",
            "task_id": r["id"],
            "owner_id": r["owner_id"],
            "employee_id": r["employee_id"],
            "objective": r["objective"],
            "constraints": json.loads(r["constraints_json"]),
            "priority": r["priority"],
            "data_policy": r["data_policy"],
            "budget_limit": (
                {"amount_minor": r["budget_amount_minor"], "currency": r["budget_currency"]}
                if r["budget_currency"]
                else None
            ),
            "completion_criteria": [
                {"criterion_id": c["id"], "description": c["description"], "required": bool(c["required"])}
                for c in criteria
            ],
            "state": r["state"],
            "blocked_reason": r["blocked_reason"],
            "version": r["version"],
            "instruction_revision": r["instruction_revision"],
            "available_actions": available_actions(r["state"], r["blocked_reason"]),
            "parent_task_id": r["parent_task_id"],
            "deadline": r["deadline"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }

    # ------------------------------------------------------------------ transitions

    def transition_in_txn(
        self,
        row: sqlite3.Row,
        to: TaskState,
        actor: Actor,
        reason: str,
        *,
        blocked_reason: str | None = None,
    ) -> int:
        """Apply one transition inside the caller's transaction. Returns the new version."""
        require_transaction(self.conn)
        src = row["state"]
        check_transition(src, to)
        if (to == TaskState.BLOCKED) != (blocked_reason is not None):
            raise _err(
                ErrorCode.INVALID_INPUT, "BLOCKED requires a blocked_reason and only BLOCKED may carry one"
            )
        leaving_running = src == TaskState.RUNNING and to != TaskState.RUNNING
        paused_from = src if to == TaskState.PAUSED else None
        new_version = int(row["version"]) + 1
        cur = self.conn.execute(
            "UPDATE tasks SET state = ?, blocked_reason = ?, paused_from = ?, version = ?, updated_at = ?,"
            " lease_owner = CASE WHEN ? THEN NULL ELSE lease_owner END,"
            " lease_expires_at = CASE WHEN ? THEN NULL ELSE lease_expires_at END,"
            " fencing_token = fencing_token + CASE WHEN ? THEN 1 ELSE 0 END"
            " WHERE id = ? AND version = ?",
            (
                to,
                blocked_reason,
                paused_from,
                new_version,
                to_utc_str(self.clock.now()),
                leaving_running,
                leaving_running,
                leaving_running,
                row["id"],
                row["version"],
            ),
        )
        if cur.rowcount != 1:
            raise _err(ErrorCode.VERSION_CONFLICT, "task changed concurrently")
        if actor.kind == "owner" and to != TaskState.PAUSED:  # the owner's own act authorizes it now (R5-03)
            self.conn.execute(
                "UPDATE tasks SET control_epoch = (SELECT control_epoch FROM employees WHERE id = ?) WHERE id = ?",
                (row["employee_id"], row["id"]),
            )
        journal.append(
            self.conn,
            self.clock,
            employee_id=row["employee_id"],
            task_id=row["id"],
            type="task.state_changed",
            actor=actor,
            summary=f"{src} -> {to}: {reason}" + (f" ({blocked_reason})" if blocked_reason else ""),
        )
        return new_version

    def transition(
        self,
        task_id: str,
        to: TaskState,
        *,
        expected_version: int,
        actor: Actor,
        reason: str,
        blocked_reason: str | None = None,
    ) -> int:
        if to == TaskState.COMPLETED:
            raise _err(ErrorCode.INVALID_INPUT, "use complete(); COMPLETED requires satisfied criteria")
        with transaction(self.conn):
            row = self._row(task_id)
            if row["version"] != expected_version:
                raise _err(
                    ErrorCode.VERSION_CONFLICT, f"expected version {expected_version}, found {row['version']}"
                )
            if row["state"] == TaskState.RUNNING and to != TaskState.RUNNING and actor.kind == "worker":
                if row["lease_owner"] != actor.id:
                    raise _err(ErrorCode.UNAUTHORIZED, "only the lease holder may move a running task")
            return self.transition_in_txn(row, to, actor, reason, blocked_reason=blocked_reason)

    # ------------------------------------------------------------------ leases

    def acquire_lease(self, task_id: str, worker_id: str) -> Lease:
        now = self.clock.now()
        with transaction(self.conn):
            row = self._row(task_id)
            if int(row["control_epoch"]) < self._epoch(row["employee_id"]) and row["state"] == TaskState.READY:
                # authorized before a stop-all that did not reach it: never executable (R5-03)
                self.transition_in_txn(row, TaskState.PAUSED, SYSTEM, "authorized before stop-all; owner must resume")
                stale = True
            else:
                stale = False
        if stale:
            raise _err(
                ErrorCode.UNAUTHORIZED,
                "task was authorized before the owner stopped everything",
                persisted="task paused",
                recommended_action="resume the task explicitly",
            )
        with transaction(self.conn):
            row = self._row(task_id)
            expired = row["lease_expires_at"] is not None and parse_utc(row["lease_expires_at"]) <= now
            if row["state"] == TaskState.RUNNING and not expired:
                raise _err(ErrorCode.VERSION_CONFLICT, "task is leased by another worker")
            if row["state"] not in (TaskState.READY, TaskState.RUNNING):
                raise _err(ErrorCode.INVALID_INPUT, f"task in {row['state']} cannot be leased")
            expires = to_utc_str(now + self.lease_ttl)
            token = int(row["fencing_token"]) + 1
            self.conn.execute(
                "UPDATE tasks SET state = 'RUNNING', lease_owner = ?, lease_expires_at = ?, fencing_token = ?,"
                " version = version + 1, updated_at = ? WHERE id = ?",
                (worker_id, expires, token, to_utc_str(now), task_id),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                task_id=task_id,
                type="task.lease_acquired",
                actor=Actor("worker", worker_id, "internal"),
                summary=f"lease acquired (token {token})"
                + (" after expiry of previous lease" if expired else ""),
            )
        return Lease(task_id, worker_id, token, expires)

    def check_lease_in_txn(self, task_id: str, worker_id: str, fencing_token: int) -> sqlite3.Row:
        """Called by the broker inside the dispatch transaction."""
        require_transaction(self.conn)
        row = self._row(task_id)
        if (
            row["state"] != TaskState.RUNNING
            or row["lease_owner"] != worker_id
            or int(row["fencing_token"]) != fencing_token
            or row["lease_expires_at"] is None
            or parse_utc(row["lease_expires_at"]) <= self.clock.now()
            or int(row["control_epoch"]) < self._epoch(row["employee_id"])  # stop-all since (R5-03)
        ):
            raise _err(
                ErrorCode.UNAUTHORIZED,
                "stale or invalid lease: worker may not dispatch",
                persisted="nothing dispatched",
                recommended_action="stop this worker; the task was paused, cancelled or re-leased",
            )
        return row

    def heartbeat(self, lease: Lease) -> Lease:
        with transaction(self.conn):
            self.check_lease_in_txn(lease.task_id, lease.worker_id, lease.fencing_token)
            expires = to_utc_str(self.clock.now() + self.lease_ttl)
            self.conn.execute("UPDATE tasks SET lease_expires_at = ? WHERE id = ?", (expires, lease.task_id))
        return Lease(lease.task_id, lease.worker_id, lease.fencing_token, expires)

    def release(
        self,
        lease: Lease,
        to: TaskState,
        reason: str,
        blocked_reason: str | None = None,
        notice: Notice | None = None,
    ) -> int:
        """Leave RUNNING. ``notice`` (kind, content, artifact_id) is queued for the owner in the SAME
        commit as the state change (A3-27): a task never waits for the owner without telling them.
        Returns the new task version."""
        with transaction(self.conn):
            row = self.check_lease_in_txn(lease.task_id, lease.worker_id, lease.fencing_token)
            version = self.transition_in_txn(
                row, to, Actor("worker", lease.worker_id, "internal"), reason, blocked_reason=blocked_reason
            )
            if notice is not None:
                enqueue_in_txn(
                    self.conn,
                    self.clock,
                    employee_id=row["employee_id"],
                    task_id=row["id"],
                    kind=notice[0],
                    content=notice[1],
                    artifact_id=notice[2],
                )
        return version

    # ------------------------------------------------------------------ owner controls

    def _owner_check(self, actor: Actor, row: sqlite3.Row) -> None:
        if actor.kind != "owner" or actor.id != row["owner_id"]:
            raise _err(ErrorCode.UNAUTHORIZED, "only the task owner may do this")

    def pause(self, task_id: str, *, actor: Actor, expected_version: int) -> int:
        with transaction(self.conn):
            row = self._row(task_id)
            self._owner_check(actor, row)
            if row["version"] != expected_version:
                raise _err(ErrorCode.VERSION_CONFLICT, "task changed; refresh and retry")
            return self.transition_in_txn(row, TaskState.PAUSED, actor, "paused by owner")

    def _unknown_actions(self, task_id: str) -> list[str]:
        return [
            r["id"]
            for r in self.conn.execute(
                "SELECT id FROM actions WHERE task_id = ? AND status IN ('UNKNOWN','DISPATCHING')", (task_id,)
            )
        ]

    def _resume_target(self, row: sqlite3.Row) -> tuple[TaskState, str | None]:
        if self._unknown_actions(row["id"]):
            return TaskState.BLOCKED, "EXTERNAL_EFFECT_UNKNOWN"
        origin = row["paused_from"]
        if origin in (
            TaskState.CREATED,
            TaskState.UNDERSTANDING,
            TaskState.PLANNING,
            TaskState.WAITING_USER,
            TaskState.VERIFYING,
        ):
            return TaskState(origin), None
        pending = self.conn.execute(
            "SELECT 1 FROM approvals WHERE task_id = ? AND status IN ('PENDING','APPROVED')", (row["id"],)
        ).fetchone()
        if origin == TaskState.WAITING_APPROVAL and pending:
            return TaskState.WAITING_APPROVAL, None
        # RUNNING, READY, RETRYING, BLOCKED (condition re-evaluated above) resume as READY.
        return TaskState.READY, None

    def resume(self, task_id: str, *, actor: Actor, expected_version: int) -> TaskState:
        with transaction(self.conn):
            row = self._row(task_id)
            self._owner_check(actor, row)
            if row["version"] != expected_version:
                raise _err(ErrorCode.VERSION_CONFLICT, "task changed; refresh and retry")
            if row["state"] != TaskState.PAUSED:
                raise _err(ErrorCode.INVALID_INPUT, "task is not paused")
            target, reason = self._resume_target(row)
            self.transition_in_txn(
                row, target, actor, "resumed by owner after re-evaluation", blocked_reason=reason
            )
            return target

    def reevaluate(
        self, task_id: str, *, actor: Actor, expected_version: int, budget: Any
    ) -> tuple[TaskState, str]:
        """'Reavaliar bloqueio' (A3-30): unblock only when the cause is really gone. Budget is read
        live; limits counters are reset for NO_PROGRESS/RETRY_LIMIT (the owner decided to try again);
        UNKNOWN external effects stay blocked until reconciled - a button never re-dispatches them."""
        with transaction(self.conn):
            row = self._row(task_id)
            self._owner_check(actor, row)
            if row["version"] != expected_version:
                raise _err(ErrorCode.VERSION_CONFLICT, "task changed; refresh and retry")
            if row["state"] != TaskState.BLOCKED:
                return TaskState(row["state"]), "a tarefa não está bloqueada"
            reason = row["blocked_reason"]
            if reason == "EXTERNAL_EFFECT_UNKNOWN" and self._unknown_actions(task_id):
                return TaskState.BLOCKED, (
                    "há ação com resultado incerto; é preciso conferir (reconciliar) antes de continuar"
                )
            if reason == "BUDGET_EXCEEDED":
                lim = budget.limits
                task_used = budget._committed("task", task_id)
                from security.budget.budget import period_key

                period_used = budget._committed("period", period_key(self.clock))
                if (
                    lim.monthly_limit_minor is None
                    or lim.per_task_limit_minor is None
                    or task_used >= lim.per_task_limit_minor
                    or period_used >= lim.monthly_limit_minor
                ):
                    return TaskState.BLOCKED, "o orçamento continua esgotado; aumente o teto em Configurações"
            if reason in ("NO_PROGRESS", "RETRY_LIMIT"):
                self.conn.execute(
                    "UPDATE task_progress SET transient_failures = 0, replans_without_progress = 0,"
                    " steps_without_verified = 0, next_attempt_at = NULL WHERE task_id = ?",
                    (task_id,),
                )
            self.transition_in_txn(row, TaskState.READY, actor, f"owner re-evaluated block ({reason})")
            return TaskState.READY, "condição reavaliada; a tarefa voltou para a fila"

    def cancel(self, task_id: str, *, actor: Actor, expected_version: int) -> CancelReport:
        """Stop future dispatches. Effects that already happened are reported, never undone (spec 12.3)."""
        report = CancelReport(task_id)
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            row = self._row(task_id)
            self._owner_check(actor, row)
            if row["version"] != expected_version:
                raise _err(ErrorCode.VERSION_CONFLICT, "task changed; refresh and retry")
            for a in self.conn.execute(
                "SELECT id, status FROM actions WHERE task_id = ? ORDER BY created_at", (task_id,)
            ).fetchall():
                if a["status"] in ("PROPOSED", "AUTHORIZED"):
                    self.conn.execute(
                        "UPDATE actions SET status = 'CANCELLED_BEFORE_DISPATCH', status_reason = 'TASK_CANCELLED',"
                        " updated_at = ? WHERE id = ?",
                        (now, a["id"]),
                    )
                    report.cancelled_actions.append(a["id"])
                elif a["status"] == "CONFIRMED":
                    report.effects_already_happened.append(a["id"])
                elif a["status"] in ("DISPATCHING", "UNKNOWN"):
                    report.effects_uncertain.append(a["id"])
            for ap in self.conn.execute(
                "SELECT id FROM approvals WHERE task_id = ? AND status IN ('PENDING','APPROVED')", (task_id,)
            ).fetchall():
                self.conn.execute(
                    "UPDATE approvals SET status = 'REVOKED', decided_at = ? WHERE id = ?", (now, ap["id"])
                )
                report.revoked_approvals.append(ap["id"])
            self.transition_in_txn(
                row,
                TaskState.CANCELLED,
                actor,
                f"cancelled by owner; {len(report.effects_already_happened)} confirmed effect(s) preserved,"
                f" {len(report.effects_uncertain)} uncertain",
            )
        return report

    def instructions(self, task_id: str) -> list[dict[str, Any]]:
        """Every instruction revision, oldest first (the last one is in force), with its class and origin
        (R5-01). A legacy revision without a recorded class is re-derived, never assumed INTERNAL."""
        policy = self._row(task_id)["data_policy"]
        return [
            {
                "revision": r["revision"],
                "kind": r["kind"],
                "instruction": r["instruction"],
                "material": bool(r["material"]),
                "classification": instruction_classification(r["classification"], r["instruction"], policy),
                "source_message_id": r["source_message_id"],
                "content_sha256": r["content_sha256"],
            }
            for r in self.conn.execute(
                "SELECT revision, kind, instruction, material, classification, source_message_id, content_sha256"
                " FROM task_instruction_versions WHERE task_id = ? ORDER BY revision",
                (task_id,),
            )
        ]

    def update_instruction(
        self,
        task_id: str,
        *,
        actor: Actor,
        text: str,
        kind: str = "CORRECTION",
        material: bool = True,
        source_message_id: str | None = None,
        classification: str | None = None,
        derive: bool = True,
    ) -> int:
        """Record a new instruction revision durably (A3-03, spec 6.3). Returns the new revision.

        A material change cancels proposals not yet dispatched and revokes approvals given for the old
        instructions; the broker refuses any proposal decided under an older revision. Effects already
        dispatched are kept and reported, never undone. A correction grants no capability or budget.
        """
        if kind not in ("CORRECTION", "ANSWER", "ATTACHMENT"):
            raise _err(ErrorCode.INVALID_INPUT, f"unknown instruction kind {kind}")
        if not text.strip():
            raise _err(ErrorCode.INVALID_INPUT, "empty instruction")
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            row = self._row(task_id)
            self._owner_check(actor, row)
            if row["state"] in TERMINAL:
                raise _err(ErrorCode.INVALID_INPUT, f"task is {row['state']}; start a new task instead")
            rev = int(row["instruction_revision"]) + 1
            # R5-01: the revision inherits the class of the message it came from (and of its own words);
            # the task becomes at least that protected - copies are protected by their own lineage too.
            cls = highest(classification or "INTERNAL", self._message_class(source_message_id), classify_text(text))
            self.conn.execute(
                "INSERT INTO task_instruction_versions(task_id, revision, kind, instruction, material, author,"
                " source_message_id, created_at, classification, content_sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (task_id, rev, kind, text[:32000], int(material), f"{actor.kind}:{actor.id}", source_message_id, now,
                 cls, sha256_text(text[:32000])),
            )
            self.conn.execute(
                "UPDATE tasks SET instruction_revision = ?, version = version + 1, updated_at = ?,"
                " data_policy = ? WHERE id = ?",
                (rev, now, highest(row["data_policy"], cls), task_id),
            )
            cancelled = revoked = 0
            if material:
                for a in self.conn.execute(
                    "SELECT id FROM actions WHERE task_id = ? AND status IN ('PROPOSED','AUTHORIZED')", (task_id,)
                ).fetchall():
                    self.conn.execute(
                        "UPDATE actions SET status = 'CANCELLED_BEFORE_DISPATCH', status_reason = 'INSTRUCTION_CHANGED',"
                        " updated_at = ? WHERE id = ?",
                        (now, a["id"]),
                    )
                    cancelled += 1
                for ap in self.conn.execute(
                    "SELECT id FROM approvals WHERE task_id = ? AND status IN ('PENDING','APPROVED')", (task_id,)
                ).fetchall():
                    self.conn.execute(
                        "UPDATE approvals SET status = 'REVOKED', decided_at = ? WHERE id = ?", (now, ap["id"])
                    )
                    revoked += 1
                fresh = self._row(task_id)
                if fresh["state"] == TaskState.WAITING_APPROVAL and revoked:
                    self.transition_in_txn(fresh, TaskState.READY, actor, "approval revoked by a correction")
                criteria_note = self._rederive_criteria_in_txn(task_id, rev, kind if derive else "SYSTEM", text)
            else:
                criteria_note = "not material: evidence kept (the note does not change what is delivered)"
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                task_id=task_id,
                type="task.instruction_updated",
                actor=actor,
                summary=f"instruction revision {rev} ({kind}{', material' if material else ''}); "
                f"{cancelled} proposal(s) cancelled, {revoked} approval(s) revoked; {criteria_note}",
            )
        return rev

    def _rederive_criteria_in_txn(self, task_id: str, rev: int, kind: str, text: str) -> str:
        """A material instruction invalidates every earlier approval and adds what it asks for (R5-04).

        * all live criteria lose their evidence: they must be proven again for revision ``rev``;
        * a correction's own subject becomes a coverage criterion (terms it excludes are left out); if it
          REPLACES the subject ("abandone...", "somente sobre..."), earlier coverage is superseded;
        * each condition of the correction is a criterion; one of the same kind (a new cap, a new date)
          supersedes the earlier one instead of stacking contradictory conditions;
        * an attachment makes complete reading of the inputs a criterion.
        """
        require_transaction(self.conn)
        live = self.conn.execute(
            "SELECT id, check_kind, params_json FROM task_criteria WHERE task_id = ? AND superseded_revision IS NULL",
            (task_id,),
        ).fetchall()
        self.conn.execute(
            "UPDATE task_criteria SET satisfied_at = NULL, evidence_id = NULL WHERE task_id = ?"
            " AND superseded_revision IS NULL",
            (task_id,),
        )
        added = superseded = 0

        def add(description: str, required: bool, check: str, params: dict[str, Any]) -> None:
            nonlocal added
            self.conn.execute(
                "INSERT INTO task_criteria(id, task_id, description, required, check_kind, params_json,"
                " instruction_revision) VALUES (?,?,?,?,?,?,?)",
                (new_id(), task_id, description, int(required), check, json.dumps(params) if params else None, rev),
            )
            added += 1

        def supersede(criterion_id: str) -> None:
            nonlocal superseded
            self.conn.execute("UPDATE task_criteria SET superseded_revision = ? WHERE id = ?", (rev, criterion_id))
            superseded += 1

        if kind == "CORRECTION":
            conditions = extract_conditions(text)
            excluded = {t for c in conditions if c.kind == "EXCLUSION" for t in key_terms(c.value)}
            terms = [t for t in key_terms(text) if t not in excluded and t not in _CORRECTION_WORDS]
            if _REPLACES.search(fold(text)):
                for c in live:
                    if c["check_kind"] == "coverage":
                        supersede(c["id"])
            if terms:
                add(f"Atende à correção da revisão {rev} (aborda: {', '.join(terms)})", True, "coverage",
                    {"terms": terms, "min_ratio": 0.5})
            for cond in conditions:
                if cond.kind in ("DATE", "MONEY_CAP", "QUANTITY"):
                    for c in live:
                        params = json.loads(c["params_json"]) if c["params_json"] else {}
                        if c["check_kind"] == "condition" and params.get("kind") == cond.kind:
                            supersede(c["id"])
                add(cond.describe(), cond.kind in CHECKED_CONDITIONS, "condition", cond.as_params())
        elif kind == "ATTACHMENT" and not any(c["check_kind"] == "inputs_read" for c in live):
            add("Documentos de entrada lidos por completo", True, "inputs_read", {})
        return f"criteria: {len(live)} re-opened, {superseded} superseded, {added} added for revision {rev}"

    def accept_reduced_scope(self, task_id: str, artifact_id: str, *, actor: Actor, note: str = "") -> int:
        """The owner accepts that a PARTIAL input is analysed only in its extracted part (R5-06). Recorded
        per task and document with the exact missing areas, as a material instruction revision the model
        sees; the deliverable must still state the limitation. Returns the new revision."""
        row = self._row(task_id)
        self._owner_check(actor, row)
        ext = self.conn.execute(
            "SELECT e.state, e.missing_json, a.name FROM document_extractions e JOIN artifact_links l"
            " ON l.artifact_id = e.artifact_id AND l.task_id = ? AND l.relation = 'input'"
            " JOIN artifacts a ON a.id = e.artifact_id WHERE e.artifact_id = ?",
            (task_id, artifact_id),
        ).fetchone()
        if ext is None or ext["state"] != "PARTIAL":
            raise _err(ErrorCode.INVALID_INPUT, "only a PARTIAL input of this task can have a reduced scope")
        missing = json.loads(ext["missing_json"])
        rev = self.update_instruction(
            task_id,
            actor=actor,
            text=f"Escopo reduzido aceito pelo proprietário para «{ext['name']}»: analisar somente o que foi "
            f"extraído; não analisado: {', '.join(missing)}. Declare essa limitação na entrega."
            + (f" Observação: {note}" if note.strip() else ""),
            derive=False,  # system wording: re-opens the evidence, adds no subject to cover
        )
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR REPLACE INTO input_scope_acceptances(task_id, artifact_id, instruction_revision,"
                " missing_json, accepted_by, note, created_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, artifact_id, rev, json.dumps(missing, ensure_ascii=False), f"{actor.kind}:{actor.id}",
                 note[:1000] or None, to_utc_str(self.clock.now())),
            )
        return rev

    def stop_all(self, *, actor: Actor, employee_id: str, origin: str = "local_app") -> StopReport:
        """Authenticated "stop everything": revoke every lease and pause all active tasks (spec 12.3)."""
        started = time.perf_counter()
        report = StopReport()
        with transaction(self.conn):
            owner = self.conn.execute(
                "SELECT owner_id FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            if owner is None or actor.kind != "owner" or actor.id != owner["owner_id"]:
                raise _err(ErrorCode.UNAUTHORIZED, "only the owner can stop the employee")
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE employee_id = ? AND state NOT IN ('COMPLETED','FAILED','CANCELLED','PAUSED')"
                " ORDER BY CASE state WHEN 'RUNNING' THEN 0 ELSE 1 END",
                (employee_id,),
            ).fetchall()
            for row in rows:
                self.transition_in_txn(row, TaskState.PAUSED, actor, "stop-all by owner")
                report.paused_tasks.append(row["id"])
            for a in self.conn.execute(
                "SELECT a.id, a.status FROM actions a JOIN tasks t ON t.id = a.task_id"
                " WHERE t.employee_id = ? AND a.status IN ('DISPATCHING','UNKNOWN')",
                (employee_id,),
            ):
                (report.in_flight_actions if a["status"] == "DISPATCHING" else report.unknown_actions).append(
                    a["id"]
                )
            self.conn.execute(
                "UPDATE employees SET control_epoch = control_epoch + 1 WHERE id = ?", (employee_id,)
            )
            report.control_epoch = int(
                self.conn.execute("SELECT control_epoch FROM employees WHERE id = ?", (employee_id,)).fetchone()[0]
            )
            self.conn.execute(
                "INSERT INTO control_orders(id, employee_id, kind, control_epoch, origin, requested_at, applied_at,"
                " report_json) VALUES (?,?,'STOP_ALL',?,?,?,?,?)",
                (
                    new_id(),
                    employee_id,
                    report.control_epoch,
                    origin,
                    to_utc_str(self.clock.now()),
                    to_utc_str(self.clock.now()),
                    json.dumps(
                        {
                            "paused": report.paused_tasks,
                            "in_flight": report.in_flight_actions,
                            "unknown": report.unknown_actions,
                        }
                    ),
                ),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=employee_id,
                type="employee.stopped",
                actor=actor,
                summary=f"stop-all (epoch {report.control_epoch}): {len(report.paused_tasks)} task(s) paused, "
                f"{len(report.in_flight_actions)} action(s) already in flight",
            )
        report.elapsed_ms = (time.perf_counter() - started) * 1000
        return report

    # ------------------------------------------------------------------ completion

    def satisfy_criterion(self, task_id: str, criterion_id: str, evidence_id: str) -> None:
        with transaction(self.conn):
            ev = self.conn.execute(
                "SELECT 1 FROM evidence WHERE id = ? AND task_id = ?", (evidence_id, task_id)
            ).fetchone()
            if ev is None:
                raise _err(ErrorCode.INVALID_INPUT, "criterion needs existing evidence of this task")
            cur = self.conn.execute(
                "UPDATE task_criteria SET satisfied_at = ?, evidence_id = ? WHERE id = ? AND task_id = ?",
                (to_utc_str(self.clock.now()), evidence_id, criterion_id, task_id),
            )
            if cur.rowcount != 1:
                raise _err(ErrorCode.INVALID_INPUT, "unknown criterion")

    def complete(
        self,
        task_id: str,
        *,
        actor: Actor,
        expected_version: int,
        notice: Notice | None = None,
        expected_revision: int | None = None,
    ) -> None:
        """COMPLETED only when every required criterion has evidence (spec 15.3). The delivery notice
        commits together with the state (A3-27).

        R5-04: ``expected_revision`` is the instruction revision the deliverable was verified for; it is
        compared-and-set inside this transaction, and every live required criterion must be satisfied by
        evidence of the revision in force. A correction that landed after verification makes this fail."""
        with transaction(self.conn):
            row = self._row(task_id)
            if row["version"] != expected_version:
                raise _err(ErrorCode.VERSION_CONFLICT, "task changed; refresh and retry")
            if expected_revision is not None and int(row["instruction_revision"]) != expected_revision:
                raise _err(
                    ErrorCode.VERSION_CONFLICT,
                    f"verified for instruction revision {expected_revision}, but revision "
                    f"{row['instruction_revision']} is in force",
                )
            if row["state"] != TaskState.VERIFYING:
                raise _err(ErrorCode.INVALID_INPUT, "only a task in VERIFYING can complete")
            missing = self.conn.execute(
                "SELECT c.description FROM task_criteria c LEFT JOIN evidence e ON e.id = c.evidence_id"
                " WHERE c.task_id = ? AND c.required = 1 AND c.superseded_revision IS NULL"
                " AND (c.satisfied_at IS NULL OR COALESCE(e.instruction_revision, 0) <> ?)",
                (task_id, row["instruction_revision"]),
            ).fetchall()
            if missing:
                raise _err(
                    ErrorCode.INVALID_INPUT,
                    "required criteria not satisfied: " + "; ".join(m["description"] for m in missing),
                    recommended_action="deliver as partial (FAILED with partial deliverables) or repair",
                )
            if self._unknown_actions(task_id):
                raise _err(ErrorCode.EXTERNAL_EFFECT_UNKNOWN, "task has actions with unknown outcome")
            self.transition_in_txn(row, TaskState.COMPLETED, actor, "all required criteria satisfied")
            if notice is not None:
                enqueue_in_txn(
                    self.conn,
                    self.clock,
                    employee_id=row["employee_id"],
                    task_id=task_id,
                    kind=notice[0],
                    content=notice[1],
                    artifact_id=notice[2],
                )

    def checkpoint(self, task_id: str, state: dict[str, Any]) -> str:
        """Operational checkpoint. Private model reasoning is never stored (spec 9.3)."""
        bad = _FORBIDDEN_CHECKPOINT_KEYS & {k.lower() for k in state}
        if bad:
            raise _err(ErrorCode.INVALID_INPUT, f"checkpoint may not contain {sorted(bad)}")
        cp_id = new_id()
        with transaction(self.conn):
            self._row(task_id)
            self.conn.execute(
                "INSERT INTO checkpoints(id, task_id, state_json, created_at) VALUES (?,?,?,?)",
                (cp_id, task_id, json.dumps(state, sort_keys=True), to_utc_str(self.clock.now())),
            )
        return cp_id

    # ------------------------------------------------------------------ recovery

    def recover_after_restart(self) -> RecoveryReport:
        """Spec 12.4: expire leases, mark in-flight effects UNKNOWN, re-validate approvals, and only
        then put tasks back to READY. Nothing is re-dispatched here."""
        rep = RecoveryReport()
        now_dt = self.clock.now()
        now = to_utc_str(now_dt)
        with transaction(self.conn):
            for a in self.conn.execute("SELECT id FROM actions WHERE status = 'DISPATCHING'").fetchall():
                self.conn.execute(
                    "UPDATE actions SET status = 'UNKNOWN', status_reason = 'INTERRUPTED_BY_RESTART', updated_at = ?"
                    " WHERE id = ?",
                    (now, a["id"]),
                )
                self.conn.execute(
                    "UPDATE approval_consumptions SET status = 'HELD_UNKNOWN' WHERE action_id = ? AND status = 'RESERVED'",
                    (a["id"],),
                )
                rep.actions_marked_unknown.append(a["id"])
            for ap in self.conn.execute(
                "SELECT id, expires_at FROM approvals WHERE status IN ('PENDING','APPROVED')"
            ).fetchall():
                if parse_utc(ap["expires_at"]) <= now_dt:
                    self.conn.execute("UPDATE approvals SET status = 'EXPIRED' WHERE id = ?", (ap["id"],))
                    rep.approvals_expired.append(ap["id"])
            for row in self.conn.execute("SELECT * FROM tasks WHERE state = 'RUNNING'").fetchall():
                rep.released_leases.append(row["id"])
                if self._unknown_actions(row["id"]):
                    self.transition_in_txn(
                        row,
                        TaskState.BLOCKED,
                        SYSTEM,
                        "restart recovery",
                        blocked_reason="EXTERNAL_EFFECT_UNKNOWN",
                    )
                    rep.tasks_blocked.append(row["id"])
                else:
                    self.transition_in_txn(row, TaskState.READY, SYSTEM, "restart recovery: lease expired")
                    rep.tasks_ready.append(row["id"])
            for row in self.conn.execute("SELECT * FROM tasks WHERE state = 'READY'").fetchall():
                if self._unknown_actions(row["id"]):
                    self.transition_in_txn(
                        row,
                        TaskState.BLOCKED,
                        SYSTEM,
                        "restart recovery",
                        blocked_reason="EXTERNAL_EFFECT_UNKNOWN",
                    )
                    rep.tasks_blocked.append(row["id"])
            for emp in self.conn.execute("SELECT id FROM employees").fetchall():
                journal.append(
                    self.conn,
                    self.clock,
                    employee_id=emp["id"],
                    type="system.recovered",
                    actor=SYSTEM,
                    summary=f"recovery: {len(rep.actions_marked_unknown)} action(s) UNKNOWN, "
                    f"{len(rep.tasks_blocked)} task(s) blocked, {len(rep.tasks_ready)} back to READY",
                )
        return rep

    def unblock_if_resolved(self, task_id: str, *, actor: Actor) -> TaskState:
        """After reconciliation, a task blocked on unknown effects returns to READY only when none remain."""
        with transaction(self.conn):
            row = self._row(task_id)
            if row["state"] != TaskState.BLOCKED:
                return TaskState(row["state"])
            if row["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN" and self._unknown_actions(task_id):
                return TaskState.BLOCKED
            self.transition_in_txn(row, TaskState.READY, actor, "blocking condition resolved")
            return TaskState.READY


def available_actions(state: str, blocked_reason: str | None) -> list[str]:
    """What the owner may do now (A3-30, spec 6.1). The UI shows exactly these; nothing is guessed."""
    if state in ("COMPLETED", "FAILED", "CANCELLED"):
        return []
    if state == "PAUSED":
        return ["resume", "cancel"]
    if state == "BLOCKED":
        return ["reconcile" if blocked_reason == "EXTERNAL_EFFECT_UNKNOWN" else "reevaluate", "cancel"]
    return ["pause", "cancel"]


def is_terminal(state: str) -> bool:
    return TaskState(state) in TERMINAL
