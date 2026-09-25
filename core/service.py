"""atlas-core request handling (spec 13.5, 3.3; review Etapa 3).

Every request is validated against ``ipc_request.schema.json``; the actor comes from the session.
Conversation semantics follow the spec: a message is persisted before anything is claimed, "pare"
changes operational state (revokes leases and asks in-flight operations to stop), and the reply only
mentions a task that really exists. Methods whose component is not built yet answer with an explicit
error (never a simulated success).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any

from core.conversation import ConversationService
from core.health import WorkerMonitor
from core.intelligence import IntelligenceSetup
from core.ipc.sessions import Session
from runtime.artifacts.manager import ArtifactManager
from runtime.artifacts.uploads import UploadStore, staging_path
from runtime.memory.manager import MemoryManager
from runtime.tasks.engine import TaskEngine
from runtime.verification.criteria import derive_criteria
from security.approvals.engine import ApprovalEngine
from security.broker.broker import Broker
from shared.clock import Clock, to_utc_str
from shared.config import parse_config
from shared.contracts import ContractError, errors_for
from shared.errors import AtlasError, ErrorCode
from shared.money import Money
from storage import journal
from storage.db import transaction

OWNER_ONLY = {
    "tasks.pause",
    "tasks.resume",
    "tasks.cancel",
    "tasks.reevaluate",
    "capabilities.decide",
    "approvals.decide",
    "memories.propose",
    "memories.correct",
    "memories.delete",
    "settings.update",
    "credentials.register",
    "intelligence.check",
    "memories.confirm",
    "memories.export",
    "artifacts.upload",
    "artifacts.import",
}
OWNER_OR_DEVICE = {"conversations.send", "tasks.create", "control.stop", "tasks.update_instruction"}


class CoreService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        broker: Broker,
        version: str = "0.1.0",
        *,
        intelligence: IntelligenceSetup | None = None,
        artifacts: ArtifactManager | None = None,
        worker: WorkerMonitor | None = None,
    ) -> None:
        self.conn = conn
        self.worker = worker
        self.clock = clock
        self.broker = broker
        self.tasks: TaskEngine = broker.tasks
        self.approvals: ApprovalEngine = broker.approvals
        self.memory = MemoryManager(conn, clock)
        self.version = version
        self.intelligence = intelligence
        self.artifacts = artifacts
        self.conversation = ConversationService(conn, clock, broker, intelligence)
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
            "identity.get": self._identity,
            "credentials.register": self._credentials_register,
            "intelligence.check": self._intelligence_check,
            "artifacts.list": self._artifacts_list,
            "approvals.list": self._approvals_list,
            "settings.get": self._settings_get,
            "conversations.current": self._conv_current,
            "conversations.history": self._conv_history,
            "memories.confirm": self._mem_confirm,
            "artifacts.upload": self._upload,
            "artifacts.import": self._import,
            "artifacts.read": self._read,
            "control.stop": self._control_stop,
            "tasks.reevaluate": self._task_reevaluate,
            "memories.forget_preview": self._mem_forget_preview,
            "memories.list": self._mem_list,
            "memories.export": self._mem_export,
            "artifacts.all": self._artifacts_all,
            "capabilities.list": self._capabilities_list,
            "capabilities.decide": self._capabilities_decide,
            "tasks.update_instruction": self._update_instruction,
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
        row = self.conn.execute("SELECT employee_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or row[0] != session.employee_id:  # same answer for "absent" and "not yours"
            raise AtlasError(ErrorCode.INVALID_INPUT, "task not found for this employee")
        return self.tasks.get(task_id)

    # ------------------------------------------------------------------ handlers

    def _health(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self.conn.execute("SELECT 1").fetchone()
        intel = self.intelligence.status() if self.intelligence else None
        worker = self.worker.snapshot() if self.worker else {"state": "not_started", "last_error": None}
        return {
            # "connected" is not "able to execute": a missing or failed executor is never reported as ok
            "status": "ok" if worker["state"] == "ok" else "degraded",
            "version": self.version,
            "worker": worker,
            "components": {
                "worker": worker["state"],
                "database": "ok",
                "workspace": "not_available",
                "voice": "not_available",
                "remote_channel": "not_available",
                "intelligence": "ready" if intel and intel.configured else "not_configured",
            },
            "intelligence_reason": intel.reason if intel else "intelligence setup not loaded",
        }

    def _send(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        out = self.conversation.handle(self._owner_actor(s), s.employee_id, p)
        return {
            **out,
            "message_id": out["message"]["message_id"],
            "control": "stopped" if out["intent"] == "control" else None,
            "paused_tasks": out.get("paused", []),
        }

    def _conv_current(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        return {"conversation_id": self.conversation.current(s.employee_id)}

    def _conv_history(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        return self.conversation.history(
            p["conversation_id"],
            s.employee_id,
            p.get("before_message_id"),
            int(p.get("limit", 50)),
            after_sequence=p.get("after_sequence"),
            changed_since_revision=p.get("changed_since_revision"),
        )

    def _task_create(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        for aid in p["artifact_ids"]:  # validate every attachment before creating anything
            row = self.conn.execute("SELECT employee_id FROM artifacts WHERE id = ?", (aid,)).fetchone()
            if row is None or row[0] != s.employee_id:
                raise AtlasError(ErrorCode.INVALID_INPUT, "artifact not found for this employee")
        if "conversation_id" in p:
            conv = self.conn.execute(
                "SELECT employee_id FROM conversations WHERE id = ?", (p["conversation_id"],)
            ).fetchone()
            if conv is None or conv[0] != s.employee_id:
                raise AtlasError(ErrorCode.INVALID_INPUT, "conversation not found for this employee")
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
            criteria=[
                (c.description, c.required, c.kind, c.params)
                for c in derive_criteria(p["objective"], bool(p["artifact_ids"]))
            ],
            conversation_id=p.get("conversation_id"),
            client_request_id=p.get("client_request_id"),
            input_artifact_ids=p["artifact_ids"],  # same commit as the task (A3-12)
        )
        return {"task": self.tasks.get(tid)}  # the task exists before anyone says "started"

    def _control_stop(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """Priority control lane (A3-04, spec 6.2): no model, no conversation routing, no upload queue.

        Persists the order and the new control epoch, revokes every lease (fencing) and asks in-flight
        operations to stop. What was already sent is reported as happened/uncertain, never as undone.
        """
        actor = self._owner_actor(s)
        origin = "local_app" if s.actor.channel == "local_app" else "paired_device"
        rep = self.tasks.stop_all(actor=actor, employee_id=s.employee_id, origin=origin)
        cancel_requested: list[str] = []
        for tid in rep.paused_tasks:
            cancel_requested += self.broker.request_cancel(tid)
        return {
            "stopped": True,
            "control_epoch": rep.control_epoch,
            "paused_tasks": rep.paused_tasks,
            "in_flight_actions": rep.in_flight_actions,
            "cancel_requested": cancel_requested,
            "unknown_actions": rep.unknown_actions,
            "elapsed_ms": round(rep.elapsed_ms, 2),
        }

    def _update_instruction(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """Explicit correction of one task (A3-03): same path as a correction typed in the conversation."""
        task = self._check_task(s, p["task_id"])
        conv = self.conn.execute("SELECT conversation_id FROM tasks WHERE id = ?", (p["task_id"],)).fetchone()[0]
        cid = conv or self.conversation.current(s.employee_id)
        out = self.conversation.handle(
            self._owner_actor(s),
            s.employee_id,
            {
                "conversation_id": cid,
                "client_message_id": p["client_message_id"],
                "text": p["text"],
                "task_id": task["task_id"],
            },
        )
        return {**out, "message_id": out["message"]["message_id"]}

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

    def _task_reevaluate(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """A3-30: re-check the blocking condition with current data; never re-dispatch an UNKNOWN effect."""
        self._check_task(s, p["task_id"])
        state, why = self.tasks.reevaluate(
            p["task_id"], actor=s.actor, expected_version=p["expected_version"], budget=self.broker.budget
        )
        return {"task": self.tasks.get(p["task_id"]), "state": str(state), "explanation": why}

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
        mid = self.memory.propose(  # the source must belong to this employee (checked inside, A3-26)
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
        source_id = p.get("source_id") or self.memory.add_source(  # the owner correcting on the Memory screen
            actor=s.actor, kind="owner_message", ref="app:memory-screen", employee_id=s.employee_id
        )
        v = self.memory.correct(
            p["memory_id"],
            actor=s.actor,
            expected_version=p["expected_version"],
            content=p["content"],
            source_id=source_id,
            employee_id=s.employee_id,  # session -> employee -> memory (A3-26)
            change_validity=bool(p.get("change_validity", False)),  # A3-16: window kept unless asked
            **{k: p[k] for k in ("valid_from", "valid_until") if k in p},
        )
        return {"memory_id": p["memory_id"], "version": v}

    def _mem_delete(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self.memory.require_owned(p["memory_id"], s.employee_id)
        reach = self.memory.delete(p["memory_id"], actor=s.actor, scope=p.get("scope", "erase"))
        return {"memory_id": p["memory_id"], "deleted": True, **reach}

    def _capabilities_list(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        from runtime.capabilities.requests import CapabilityRequests

        return {"requests": CapabilityRequests(self.conn, self.clock).pending(s.employee_id)}

    def _capabilities_decide(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        from runtime.capabilities.requests import CapabilityRequests

        row = self.conn.execute("SELECT employee_id FROM capability_requests WHERE id = ?", (p["request_id"],)).fetchone()
        if row is None or row[0] != s.employee_id:
            raise AtlasError(ErrorCode.INVALID_INPUT, "capability request not found for this employee")
        return CapabilityRequests(self.conn, self.clock).decide(
            p["request_id"], actor=s.actor, approve=p["decision"] == "APPROVE", note=p.get("note", "")
        )

    def _mem_list(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        statuses = tuple(p.get("statuses") or ("proposed", "confirmed", "disputed"))
        return {"memories": self.memory.list_for_owner(s.employee_id, statuses, int(p.get("limit", 200)))}

    def _mem_export(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        if s.actor.kind != "owner":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner exports memories")
        return self.memory.export_for_owner(s.employee_id)

    def _artifacts_all(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """The Files screen (spec 21.2): inputs and outputs, versions, and what was understood of each."""
        rows = self.conn.execute(
            "SELECT a.id, a.name, a.version, a.mime_type, a.size_bytes, a.sha256, a.task_id, a.classification,"
            " a.created_at, (SELECT relation FROM artifact_links l WHERE l.artifact_id = a.id LIMIT 1) AS relation,"
            " (SELECT state FROM document_extractions e WHERE e.artifact_id = a.id) AS analysis_state"
            " FROM artifacts a WHERE a.employee_id = ? ORDER BY a.created_at DESC LIMIT ?",
            (s.employee_id, int(p.get("limit", 200))),
        ).fetchall()
        return {"artifacts": [dict(r) for r in rows]}

    def _mem_forget_preview(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self.memory.require_owned(p["memory_id"], s.employee_id)
        return {"memory_id": p["memory_id"], **self.memory.forget_preview(p["memory_id"])}

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
        return {"revision": current + 1, "settings": cfg}

    def _settings_get(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """The app always starts from the saved revision (review A1): no hard-coded expected_revision."""
        row = self.conn.execute(
            "SELECT revision, config_json FROM settings ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        intel = self.intelligence.status() if self.intelligence else None
        return {
            "revision": int(row[0]) if row else 0,
            "settings": json.loads(row[1]) if row else None,
            "price_table": intel.price_table if intel else None,
            "prices_verified": bool(intel.prices_verified) if intel else False,
            "intelligence": {
                "configured": bool(intel and intel.configured),
                "reason": intel.reason if intel else "intelligence setup not loaded",
                "model_id": intel.model_id if intel else None,
                "mode": (json.loads(row[1])["intelligence"].get("mode") if row else None),
                # per profile: validated? priced? - the UI lists what still needs a check (spec 11.4)
                "profiles": self.intelligence.profiles(json.loads(row[1])) if (row and self.intelligence) else [],
            },
        }

    # ------------------------------------------------------------------ app support (Alpha)

    def _identity(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT e.id, e.name, e.locale, e.timezone, o.display_name FROM employees e"
            " JOIN owners o ON o.id = e.owner_id WHERE e.id = ?",
            (s.employee_id,),
        ).fetchone()
        return {
            "employee_id": row[0],
            "name": row[1],
            "locale": row[2],
            "timezone": row[3],
            "owner_name": row[4],
            "actor_kind": s.actor.kind,
            "settings_revision": int(
                self.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM settings").fetchone()[0]
            ),
        }

    def _credentials_register(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        if self.intelligence is None:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "credential store is not available")
        if s.actor.channel != "local_app":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "credentials are registered only on the local app")
        try:
            secret = base64.b64decode(p["secret_b64"], validate=True)
        except (binascii.Error, ValueError):
            raise AtlasError(ErrorCode.INVALID_INPUT, "secret is not valid base64") from None
        ref = self.intelligence.register_key(actor=s.actor, employee_id=s.employee_id, secret=secret)
        return {"credential_ref": ref}  # never echoes the secret

    def _intelligence_check(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        if self.intelligence is None:
            raise AtlasError(ErrorCode.MODEL_UNSUPPORTED, "intelligence setup not loaded")
        return {
            "report": self.intelligence.run_check(
                actor=s.actor,
                employee_id=s.employee_id,
                model_id=p["model_id"],
                max_cost_minor=p["max_cost_minor"],
            )
        }

    def _artifacts_list(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self._check_task(s, p["task_id"])
        rows = self.conn.execute(
            "SELECT a.id, a.name, a.version, a.sha256, a.size_bytes, a.mime_type, l.relation FROM artifact_links l"
            " JOIN artifacts a ON a.id = l.artifact_id WHERE l.task_id = ? ORDER BY a.created_at",
            (p["task_id"],),
        ).fetchall()
        return {
            "artifacts": [
                {
                    "artifact_id": r[0],
                    "name": r[1],
                    "version": r[2],
                    "sha256": r[3],
                    "size_bytes": r[4],
                    "mime_type": r[5],
                    "relation": r[6],
                }
                for r in rows
            ]
        }

    def _approvals_list(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT a.id FROM approvals a JOIN tasks t ON t.id = a.task_id WHERE t.employee_id = ?"
            " AND a.status = 'PENDING' ORDER BY a.created_at",
            (s.employee_id,),
        ).fetchall()
        return {"approvals": [self.approvals.get(r[0]) for r in rows]}

    # ------------------------------------------------------------------ memory confirmation (Alpha 2)

    def _mem_confirm(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        self.memory.require_owned(p["memory_id"], s.employee_id)
        self.memory.confirm(p["memory_id"], actor=s.actor)
        return {"memory_id": p["memory_id"], "status": "confirmed"}

    # ------------------------------------------------------------------ attachments (Alpha 2, review A4)

    def _artifact_store(self) -> ArtifactManager:
        if self.artifacts is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "artifact store is not available")
        return self.artifacts

    def _uploads(self) -> UploadStore:
        return UploadStore(self.conn, self.clock, self._artifact_store().root)

    def _upload(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """Chunked copy of ONE file the owner picked; the core never touches the original on disk.

        Coordinated through ``upload_sessions`` (A3-24): every connection sees the same offsets, quota
        and expiry, and an identical resend is answered as a duplicate instead of being appended twice.
        """
        if s.actor.channel != "local_app":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "attachments are added on the local app")
        try:
            chunk = base64.b64decode(p["data_b64"], validate=True)
        except (binascii.Error, ValueError):
            raise AtlasError(ErrorCode.INVALID_INPUT, "chunk is not valid base64") from None
        res = self._uploads().append(s.employee_id, p["upload_ref"], p["offset"], chunk)
        return {"upload_ref": p["upload_ref"], "received_bytes": res.received_bytes, "duplicate": res.duplicate}

    def _artifact_reply(self, art: Any, recovered: bool) -> dict[str, Any]:
        return {
            "artifact_id": art.id,
            "name": art.name,
            "mime_type": art.mime_type,
            "sha256": art.sha256,
            "size_bytes": art.size_bytes,
            "version": art.version,
            "classification": art.classification,
            "recovered": recovered,
        }

    def _import(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """Finalize an upload. Idempotent per upload_ref: a lost reply is recovered, never duplicated."""
        store = self._artifact_store()
        uploads = self._uploads()
        if "task_id" in p:
            self._check_task(s, p["task_id"])
        sess = uploads.session(s.employee_id, p["upload_ref"])
        if sess is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "upload not found; send the file again")
        if sess["state"] == "IMPORTED":
            return self._artifact_reply(store.get(sess["artifact_id"]), recovered=True)
        if sess["state"] != "RECEIVING":
            raise AtlasError(ErrorCode.INVALID_INPUT, f"upload {sess['state'].lower()}; send the file again")
        path = staging_path(store.root, s.employee_id, p["upload_ref"])
        if not path.is_file():
            raise AtlasError(ErrorCode.INVALID_INPUT, "upload not found; send the file again")
        try:
            art = store.import_file(
                path,
                actor=s.actor,
                employee_id=s.employee_id,
                declared_name=p["declared_name"],
                task_id=p.get("task_id"),
                classification=p.get("classification", "INTERNAL"),
                expected_sha256=p.get("expected_sha256"),
                on_insert_in_txn=lambda aid: uploads.mark_imported_in_txn(s.employee_id, p["upload_ref"], aid),
            )
        except AtlasError as exc:
            if exc.code == ErrorCode.VERSION_CONFLICT:  # another connection finalized it first
                again = uploads.session(s.employee_id, p["upload_ref"])
                if again is not None and again["state"] == "IMPORTED":
                    return self._artifact_reply(store.get(again["artifact_id"]), recovered=True)
            uploads.fail(s.employee_id, p["upload_ref"], exc.message)  # rejected: staging removed, explained
            raise
        path.unlink(missing_ok=True)
        return {**self._artifact_reply(art, recovered=False), "analysis": self._analysis(art.id)}

    def _analysis(self, artifact_id: str) -> dict[str, Any]:
        """A3-09: say per file whether it is understood, partly understood or only stored."""
        from runtime.documents.store import DocumentStore

        return DocumentStore(self.conn, self.clock, self._artifact_store()).ensure_extracted(artifact_id)

    def _read(self, s: Session, p: dict[str, Any]) -> dict[str, Any]:
        """Chunked read: the app previews as plain text or saves a copy and verifies the hash itself."""
        store = self._artifact_store()
        row = self.conn.execute(
            "SELECT employee_id FROM artifacts WHERE id = ?", (p["artifact_id"],)
        ).fetchone()
        if row is None or row[0] != s.employee_id:
            raise AtlasError(ErrorCode.INVALID_INPUT, "artifact not found for this employee")
        art = store.get(p["artifact_id"])
        chunk, total = store.read_range(p["artifact_id"], p["offset"], p["length"])  # linear cost (A3-25)
        return {
            "artifact_id": art.id,
            "name": art.name,
            "mime_type": art.mime_type,
            "sha256": art.sha256,
            "size_bytes": art.size_bytes,
            "offset": p["offset"],
            "data_b64": base64.b64encode(chunk).decode("ascii"),
            "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
            "eof": p["offset"] + len(chunk) >= total,
        }
