"""atlas-core request handling (spec 13.5, 3.3; review Etapa 3).

Every request is validated against ``ipc_request.schema.json``; the actor comes from the session.
Conversation semantics follow the spec: a message is persisted before anything is claimed, "pare"
changes operational state (revokes leases and asks in-flight operations to stop), and the reply only
mentions a task that really exists. Methods whose component is not built yet answer with an explicit
error (never a simulated success).
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Callable
from typing import Any

from core.ipc.sessions import Session
from runtime.memory.manager import MemoryManager
from runtime.tasks.engine import TaskEngine
from security.approvals.engine import ApprovalEngine
from security.broker.broker import Broker
from shared.clock import Clock, to_utc_str
from shared.config import parse_config
from shared.contracts import ContractError, errors_for
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.money import Money
from storage import journal
from storage.db import transaction

STOP_WORDS = {"pare", "pare tudo", "parar", "stop", "stop all", "pause tudo", "pausa tudo"}
OWNER_ONLY = {
    "tasks.pause",
    "tasks.resume",
    "tasks.cancel",
    "approvals.decide",
    "memories.propose",
    "memories.correct",
    "memories.delete",
    "settings.update",
    "artifacts.export",
}
OWNER_OR_DEVICE = {"conversations.send", "tasks.create"}


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.strip().lower().rstrip("!.")).encode("ascii", "ignore").decode()
    return " ".join(nfkd.split())


class CoreService:
    def __init__(
        self, conn: sqlite3.Connection, clock: Clock, broker: Broker, version: str = "0.1.0"
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.broker = broker
        self.tasks: TaskEngine = broker.tasks
        self.approvals: ApprovalEngine = broker.approvals
        self.memory = MemoryManager(conn, clock)
        self.version = version
        self.handlers: dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {
            "system.health": self._health,
            "conversations.send": self._send,
            "tasks.create": self._task_create,
            "tasks.get": self._task_get,
            "tasks.list": self._task_list,
            "tasks.pause": self._task_pause,
            "tasks.resume": self._task_resume,
            "tasks.cancel": self._task_cancel,
            "approvals.get": self._approval_get,
            "approvals.decide": self._approval_decide,
            "memories.search": self._mem_search,
            "memories.propose": self._mem_propose,
            "memories.correct": self._mem_correct,
            "memories.delete": self._mem_delete,
            "events.subscribe": self._events,
            "settings.validate": self._settings_validate,
            "settings.update": self._settings_update,
        }

    # ------------------------------------------------------------------ dispatch

    def handle(self, session: Session, request: Any) -> dict[str, Any]:
        rid = request.get("id") if isinstance(request, dict) else None
        corr = None
        try:
            errs = errors_for("ipc_request", request)
            if errs:
                raise AtlasError(ErrorCode.INVALID_INPUT, "invalid request: " + "; ".join(errs[:3]))
            params = request["params"]
            corr = params.get("correlation_id")
            method = request["method"]
            self._authorize(session, method, params)
            handler = self.handlers.get(method)
            if handler is None:
                code = (
                    ErrorCode.WORKSPACE_OFFLINE
                    if method.startswith("workspace.")
                    else ErrorCode.INVALID_INPUT
                )
                raise AtlasError(
                    code,
                    f"{method} is not available in this build",
                    recommended_action="see docs/PROGRESS.md for the component status",
                )
            return {"jsonrpc": "2.0", "id": rid, "result": handler(session, params)}
        except AtlasError as exc:
            return {
                "jsonrpc": "2.0",
                "id": rid if isinstance(rid, str) else None,
                "error": exc.to_jsonrpc(corr),
            }
        except ContractError as exc:
            err = AtlasError(ErrorCode.INVALID_INPUT, str(exc)[:500])
            return {
                "jsonrpc": "2.0",
                "id": rid if isinstance(rid, str) else None,
                "error": err.to_jsonrpc(corr),
            }
        except Exception:
            err = AtlasError(ErrorCode.INTERNAL_ERROR, "internal error; see local diagnostics")
            return {
                "jsonrpc": "2.0",
                "id": rid if isinstance(rid, str) else None,
                "error": err.to_jsonrpc(corr),
            }

    def _authorize(self, session: Session, method: str, params: dict[str, Any]) -> None:
        kind = session.actor.kind
        if method in OWNER_ONLY and kind != "owner":
            raise AtlasError(ErrorCode.UNAUTHORIZED, f"{method} requires the owner")
        if method in OWNER_OR_DEVICE and kind not in ("owner", "device"):
            raise AtlasError(ErrorCode.UNAUTHORIZED, f"{method} requires the owner or a paired device")
        emp = params.get("employee_id")
        if emp is not None and emp != session.employee_id:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "session is bound to another employee")

    def _owner_actor(self, session: Session) -> Any:
        """A paired device acts on behalf of the owner but keeps its channel (no strong auth)."""
        a = session.actor
        if a.kind == "device":
            owner = self.conn.execute(
                "SELECT owner_id FROM employees WHERE id = ?", (session.employee_id,)
            ).fetchone()[0]
            from shared.actors import Actor

            return Actor("owner", owner, "paired_device", strong_auth=False)
        return a

    def _check_task(self, session: Session, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if task["employee_id"] != session.employee_id:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "task belongs to another employee")
        return task

    # ------------------------------------------------------------------ handlers

    def _health(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self.conn.execute("SELECT 1").fetchone()
        return {
            "status": "ok",
            "version": self.version,
            "components": {
                "database": "ok",
                "workspace": "not_available",
                "voice": "not_available",
                "remote_channel": "not_available",
            },
        }

    def _send(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        actor = self._owner_actor(s)
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            conv = self.conn.execute(
                "SELECT employee_id FROM conversations WHERE id = ?", (p["conversation_id"],)
            ).fetchone()
            if conv is None:
                self.conn.execute(
                    "INSERT INTO conversations(id, employee_id, created_at) VALUES (?,?,?)",
                    (p["conversation_id"], s.employee_id, now),
                )
            elif conv[0] != s.employee_id:
                raise AtlasError(ErrorCode.UNAUTHORIZED, "conversation belongs to another employee")
            existing = self.conn.execute(
                "SELECT id, task_id FROM messages WHERE conversation_id = ? AND client_message_id = ?",
                (p["conversation_id"], p["client_message_id"]),
            ).fetchone()
            if existing:  # idempotent resend from the client
                return {"message_id": existing[0], "task_id": existing[1], "control": None, "duplicate": True}
            mid = new_id()
            origin = "local_app" if s.actor.channel == "local_app" else "paired_device"
            self.conn.execute(
                "INSERT INTO messages(id, conversation_id, role, origin, client_message_id, content, created_at)"
                " VALUES (?,?,'owner',?,?,?,?)",
                (mid, p["conversation_id"], origin, p["client_message_id"], p["text"], now),
            )
        control = None
        paused: list[str] = []
        in_flight: list[str] = []
        if _normalize(p["text"]) in STOP_WORDS:
            rep = self.tasks.stop_all(actor=actor, employee_id=s.employee_id)
            for tid in rep.paused_tasks:
                self.broker.request_cancel(tid)
            control, paused, in_flight = "stopped", rep.paused_tasks, rep.in_flight_actions
        return {
            "message_id": mid,
            "task_id": None,
            "control": control,
            "paused_tasks": paused,
            "in_flight_actions": in_flight,
            "duplicate": False,
        }

    def _task_create(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        budget = Money.from_json(p["budget_limit"]) if "budget_limit" in p else None
        tid = self.tasks.create(
            self._owner_actor(s),
            employee_id=p["employee_id"],
            objective=p["objective"],
            external_writes=p["constraints"]["external_writes"],
            purchases=p["constraints"]["purchases"],
            priority=p.get("priority", "NORMAL"),
            budget_limit=budget,
            deadline=p.get("deadline"),
            criteria=[("Resultado entregue e verificado", True)],
        )
        for aid in p["artifact_ids"]:
            row = self.conn.execute("SELECT employee_id FROM artifacts WHERE id = ?", (aid,)).fetchone()
            if row is None or row[0] != s.employee_id:
                raise AtlasError(ErrorCode.INVALID_INPUT, "artifact not found for this employee")
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT OR IGNORE INTO artifact_links(artifact_id, task_id, relation) VALUES (?,?,'input')",
                    (aid, tid),
                )
        return {"task": self.tasks.get(tid)}  # the task exists before anyone says "started"

    def _task_get(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        return {"task": self._check_task(s, p["task_id"])}

    def _task_list(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        states = p.get("states")
        rows = self.conn.execute(
            "SELECT id, state FROM tasks WHERE employee_id = ? ORDER BY updated_at DESC LIMIT ?",
            (s.employee_id, int(p.get("limit", 100))),
        ).fetchall()
        return {"tasks": [self.tasks.get(r[0]) for r in rows if not states or r[1] in states]}

    def _task_pause(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self._check_task(s, p["task_id"])
        self.tasks.pause(p["task_id"], actor=s.actor, expected_version=p["expected_version"])
        self.broker.request_cancel(p["task_id"])
        return {"task": self.tasks.get(p["task_id"])}

    def _task_resume(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self._check_task(s, p["task_id"])
        state = self.tasks.resume(p["task_id"], actor=s.actor, expected_version=p["expected_version"])
        return {"task": self.tasks.get(p["task_id"]), "resumed_to": str(state)}

    def _task_cancel(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self._check_task(s, p["task_id"])
        in_flight = self.broker.request_cancel(p["task_id"])
        rep = self.tasks.cancel(p["task_id"], actor=s.actor, expected_version=p["expected_version"])
        return {
            "task": self.tasks.get(p["task_id"]),
            "effects_already_happened": rep.effects_already_happened,
            "effects_uncertain": rep.effects_uncertain,
            "cancel_requested_in_flight": in_flight,
        }

    def _approval_get(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        ap = self.approvals.get(p["approval_id"])
        self._check_task(s, ap["task_id"])
        return {"approval": ap}

    def _approval_decide(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        ap = self.approvals.get(p["approval_id"])
        self._check_task(s, ap["task_id"])
        decided = self.broker.decide_approval(
            p["approval_id"],
            actor=s.actor,
            approve=p["decision"] == "APPROVE",
            params_hash=p["params_hash"],
            nonce=p["nonce"],
        )
        return {"approval": decided}

    def _mem_search(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        hits = self.memory.search(employee_id=s.employee_id, query=p["query"], limit=int(p.get("limit", 20)))
        return {"hits": [h.__dict__ for h in hits]}

    def _mem_propose(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        mid = self.memory.propose(
            actor=s.actor,
            employee_id=s.employee_id,
            type=p["memory_type"],
            content=p["content"],
            source_id=p["source_id"],
            valid_from=p.get("valid_from"),
            valid_until=p.get("valid_until"),
        )
        return {"memory_id": mid}

    def _mem_correct(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        v = self.memory.correct(
            p["memory_id"],
            actor=s.actor,
            expected_version=p["expected_version"],
            content=p["content"],
            source_id=p["source_id"],
        )
        return {"memory_id": p["memory_id"], "version": v}

    def _mem_delete(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self.memory.delete(p["memory_id"], actor=s.actor)
        return {"memory_id": p["memory_id"], "deleted": True}

    def _events(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        events = journal.events_after(self.conn, s.employee_id, p["after_sequence_id"])
        return {
            "events": events,
            "last_sequence_id": events[-1]["sequence_id"] if events else p["after_sequence_id"],
        }

    def _settings_validate(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        parse_config(p["settings"])
        return {"valid": True}

    def _settings_update(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        import json

        cfg = parse_config(p["settings"])
        with transaction(self.conn):
            current = int(self.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM settings").fetchone()[0])
            if current != p["expected_revision"]:
                raise AtlasError(ErrorCode.VERSION_CONFLICT, "settings changed; refresh and retry")
            self.conn.execute(
                "INSERT INTO settings(revision, config_json, updated_at, updated_by) VALUES (?,?,?,?)",
                (
                    current + 1,
                    json.dumps(cfg, sort_keys=True),
                    to_utc_str(self.clock.now()),
                    f"{s.actor.kind}:{s.actor.id}",
                ),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=s.employee_id,
                type="settings.updated",
                actor=s.actor,
                summary=f"settings revision {current + 1}",
            )
        return {"revision": current + 1}
