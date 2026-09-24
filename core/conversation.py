"""Conversation service (spec 2.2, 3.3; review Alpha 1 A2).

One persistent conversation per employee (more can exist; none is hidden or deleted). Every owner
message is stored first, then routed deterministically where possible:

control ("pare") -> answer to a pending question -> memory request -> status query -> correction ->
explicit delegation -> free conversation (model, if configured) .

Replies are real events: a status reply is built from the database, an acknowledgement exists only
after the task exists, a question from the agent arrives as a message linked to its task, and "pare"
states what could not be undone. Nothing here creates a task for a greeting or a short reply.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator

from core.intelligence import IntelligenceSetup
from runtime.memory.knowledge import KnowledgeContextService
from runtime.memory.manager import MemoryManager
from runtime.models.context import (
    Authority,
    ContextBuilder,
    ContextItem,
    ContextOverflow,
    RequiredContextWithheld,
)
from runtime.models.router import Requirements
from runtime.models.types import ModelRequest
from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from security.broker.broker import Broker
from security.egress.guard import EgressGuard
from shared.actors import Actor
from shared.canonical import canonical_hash
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage.db import transaction

STOP_WORDS = {"pare", "pare tudo", "parar", "stop", "stop all", "pausa tudo", "pause tudo"}
# MEMORY runs on the ORIGINAL text (accents kept, exact span removed): "lembrete" is not "lembre" (A3-13).
_MEMORY = re.compile(
    r"^\s*(?:por\s+favor,?\s*)?(?:guarde|lembre-se|lembre|memorize|anote)(?=[\s:,]|$)"
    r"(?:\s+(?:esta|essa)\s+(?:prefer[eê]ncia|informa[cç][aã]o))?\s*(?:que\b|:|,)?\s*(?P<c>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_WORK = r"(?:tarefa|tarefas|trabalho|trabalhos|pedido|pedidos|entrega|entregas|servico|servicos)"
_OWN = r"(?:(?:minha|minhas|meu|meus|sua|suas|seu|seus)\s+)?"
# STATUS runs on the normalized text and needs an explicit reference to work (A3-13): "como está o
# tempo" or "o andamento da economia" are conversation, not task status.
_STATUS = re.compile(
    r"^(?:e\s+)?(?:(?:qual|como)\s+(?:e\s+|esta\s+|vai\s+|anda\s+)?(?:o\s+|a\s+|os\s+|as\s+)?)?"
    r"(?:status|andamento|progresso)(?:\s+(?:da|do|das|dos|de)\s+" + _OWN + _WORK + r")?$"
    r"|^(?:e\s+)?(?:o\s+)?que\s+(?:voce\s+)?(?:esta|anda)\s+fazendo$"
    r"|^(?:e\s+)?como\s+(?:esta|vai|anda|estao|vao)\s+(?:o|a|os|as)\s+" + _OWN + _WORK + r"$"
    r"|^(?:ja\s+)?terminou(?:\s+(?:o|a)\s+" + _WORK + r")?$"
)
_REQUEST_START = re.compile(
    r"^(?:por favor,?\s*)?(?:me\s+ajude|ajude|escreva|faca|crie|prepare|pesquise|procure|analise|compare|"
    r"resuma|envie|mande|monte|organize|calcule|traduza|revise|verifique|busque|gere|elabore)\b"
)
_STORE_ONLY = re.compile(
    r"\b(guarde|guardar|arquive|arquivar|salve|salvar|so para voce ter|para depois|para referencia)\b"
)
_CORRECTION = re.compile(r"^\s*(nao era isso|na verdade|corrigindo|correcao|mudei de ideia)\b", re.IGNORECASE)
# Conservative detector of sensitive personal data in the owner's own words (spec 9.1). A hit makes
# the message SENSITIVE: it is stored, but not sent to a cloud model without a scoped consent (A3-02).
_SENSITIVE = re.compile(
    r"\b(saude|medic|doenc|diagnost|exame|remedio|cpf|rg\b|passaporte|filh|crianc|endereco|"
    r"conta bancaria|agencia|salario|renda|religi|sexual|biometr)",
    re.IGNORECASE,
)


def classify_owner_text(text: str) -> str:
    return "SENSITIVE" if _SENSITIVE.search(normalize(text)) else "INTERNAL"
CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "reply", "objective"],
    "properties": {
        "intent": {"type": "string", "enum": ["chat", "delegate"]},
        "reply": {"type": "string", "maxLength": 4000},
        "objective": {"type": "string", "maxLength": 2000},
    },
}
_CHAT_VALIDATOR = Draft202012Validator(CHAT_SCHEMA)
PROCESSING_LEASE = timedelta(minutes=10)
SEND = "conversations.send"


@dataclass
class Receipt:
    """Durable receipt of one owner request (A3-11). ``result`` is set when it already completed."""

    key: str
    state: str
    message_id: str
    result: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    busy: bool = False
EMPLOYEE = Actor("runtime", "conversation", "internal")
# Stable order (rowid) and latest global change of each message (A3-23).
MSG = (
    "m.rowid AS sequence, (SELECT MAX(c.seq) FROM message_changes c WHERE c.message_id = m.id) AS revision, m.*"
)


def normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.strip().lower()).encode("ascii", "ignore").decode()
    return " ".join(nfkd.rstrip("!.?").split())


class ConversationService:
    def __init__(
        self, conn: sqlite3.Connection, clock: Clock, broker: Broker, intelligence: IntelligenceSetup | None
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.broker = broker
        self.tasks: TaskEngine = broker.tasks
        self.intelligence = intelligence
        self.memory = MemoryManager(conn, clock)
        self._active: tuple[str, str] | None = None  # (employee_id, request key) being processed
        self._decision: dict[str, Any] | None = None

    # ------------------------------------------------------------------ storage

    def current(self, employee_id: str) -> str:
        row = self.conn.execute(
            "SELECT id FROM conversations WHERE employee_id = ? ORDER BY created_at, rowid LIMIT 1",
            (employee_id,),
        ).fetchone()
        if row:
            return str(row[0])
        cid = new_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO conversations(id, employee_id, created_at) VALUES (?,?,?)",
                (cid, employee_id, to_utc_str(self.clock.now())),
            )
        return cid

    def _message(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": row["id"],
            "role": row["role"],
            "kind": row["kind"],
            "content": row["content"],
            "task_id": row["task_id"],
            "artifact_id": row["artifact_id"],
            "memory_id": row["memory_id"],
            "created_at": row["created_at"],
            "classification": row["classification"],
            "sequence": row["sequence"],
            "revision": row["revision"],
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        row = self.conn.execute(f"SELECT {MSG} FROM messages m WHERE m.id = ?", (message_id,)).fetchone()  # noqa: S608 - MSG is a constant column list
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown message")
        return self._message(row)

    def post_in_txn(
        self,
        conversation_id: str,
        *,
        role: str,
        kind: str,
        content: str,
        origin: str = "system",
        task_id: str | None = None,
        artifact_id: str | None = None,
        memory_id: str | None = None,
        client_message_id: str | None = None,
        classification: str = "INTERNAL",
    ) -> str:
        mid = new_id()
        self.conn.execute(
            "INSERT INTO messages(id, conversation_id, role, origin, client_message_id, content, task_id, kind,"
            " artifact_id, memory_id, created_at, classification) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                conversation_id,
                role,
                origin,
                client_message_id,
                content[:32000],
                task_id,
                kind,
                artifact_id,
                memory_id,
                to_utc_str(self.clock.now()),
                classification,
            ),
        )
        return mid

    def say(
        self,
        conversation_id: str,
        kind: str,
        content: str,
        *,
        task_id: str | None = None,
        artifact_id: str | None = None,
        memory_id: str | None = None,
        reply_marker: str | None = None,
        classification: str = "INTERNAL",
    ) -> dict[str, Any]:
        if reply_marker is not None:  # a resumed request finds its reply instead of writing it twice
            existing = self.conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND client_message_id = ?",
                (conversation_id, reply_marker),
            ).fetchone()
            if existing:
                return self.get_message(existing[0])
        with transaction(self.conn):
            mid = self.post_in_txn(
                conversation_id,
                role="employee",
                kind=kind,
                content=content,
                task_id=task_id,
                artifact_id=artifact_id,
                memory_id=memory_id,
                client_message_id=reply_marker,
                classification=classification,
            )
        return self.get_message(mid)

    def history(
        self,
        conversation_id: str,
        employee_id: str,
        before_message_id: str | None,
        limit: int,
        *,
        after_sequence: int | None = None,
        changed_since_revision: int | None = None,
    ) -> dict[str, Any]:
        """Paged history. ``after_sequence`` returns everything after the client's last confirmed
        message (oldest first, no gaps); ``changed_since_revision`` returns messages created OR changed
        since that revision, so the client upserts them (A3-23)."""
        conv = self.conn.execute(
            "SELECT employee_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if conv is None or conv[0] != employee_id:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "conversation belongs to another employee")
        if changed_since_revision is not None:
            rows = self.conn.execute(
                f"SELECT {MSG} FROM messages m WHERE m.conversation_id = ? AND m.id IN"  # noqa: S608 - MSG is a constant column list
                " (SELECT message_id FROM message_changes WHERE seq > ?) ORDER BY m.rowid LIMIT ?",
                (conversation_id, changed_since_revision, limit + 1),
            ).fetchall()
            has_more = len(rows) > limit
            return {
                "conversation_id": conversation_id,
                "messages": [self._message(r) for r in rows[:limit]],
                "has_more": has_more,
            }
        if after_sequence is not None:
            rows = self.conn.execute(
                f"SELECT {MSG} FROM messages m WHERE m.conversation_id = ? AND m.rowid > ? ORDER BY m.rowid LIMIT ?",  # noqa: S608 - MSG is a constant column list
                (conversation_id, after_sequence, limit + 1),
            ).fetchall()
            has_more = len(rows) > limit
            return {
                "conversation_id": conversation_id,
                "messages": [self._message(r) for r in rows[:limit]],
                "has_more": has_more,
            }
        if before_message_id:
            ref = self.conn.execute(
                "SELECT rowid FROM messages WHERE id = ? AND conversation_id = ?",
                (before_message_id, conversation_id),
            ).fetchone()
            if ref is None:
                raise AtlasError(ErrorCode.INVALID_INPUT, "unknown message in this conversation")
            rows = self.conn.execute(
                f"SELECT {MSG} FROM messages m WHERE m.conversation_id = ? AND m.rowid < ? ORDER BY m.rowid DESC LIMIT ?",  # noqa: S608 - MSG is a constant column list
                (conversation_id, ref[0], limit + 1),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT {MSG} FROM messages m WHERE m.conversation_id = ? ORDER BY m.rowid DESC LIMIT ?",  # noqa: S608 - MSG is a constant column list
                (conversation_id, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        page = [self._message(r) for r in reversed(rows[:limit])]
        return {"conversation_id": conversation_id, "messages": page, "has_more": has_more}

    # ------------------------------------------------------------------ worker notifications

    def notify(
        self, task_id: str, kind: str, content: str, artifact_id: str | None = None
    ) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT conversation_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or row[0] is None:
            return None
        return self.say(row[0], kind, content, task_id=task_id, artifact_id=artifact_id)

    # ------------------------------------------------------------------ routing

    @staticmethod
    def payload_hash(p: dict[str, Any]) -> str:
        """The immutable envelope: everything that changes what the request means (A3-11, A3-22)."""
        return canonical_hash(
            {
                "conversation_id": p["conversation_id"],
                "text": p["text"],
                "intent": p.get("intent", "auto"),
                "artifact_ids": list(p.get("artifact_ids", [])),
                "reply_to_message_id": p.get("reply_to_message_id"),
                "task_id": p.get("task_id"),
            }
        )

    def receive(self, actor: Actor, employee_id: str, p: dict[str, Any], *, claim: bool) -> Receipt:
        """One transaction: receipt + owner message (A3-11, spec 5.1). Returns what to do next."""
        cid = p["conversation_id"]
        key = p["client_message_id"]
        digest = self.payload_hash(p)
        now_dt = self.clock.now()
        now = to_utc_str(now_dt)
        lease = to_utc_str(now_dt + PROCESSING_LEASE)
        with transaction(self.conn):
            conv = self.conn.execute("SELECT employee_id FROM conversations WHERE id = ?", (cid,)).fetchone()
            if conv is None:
                self.conn.execute(
                    "INSERT INTO conversations(id, employee_id, created_at) VALUES (?,?,?)", (cid, employee_id, now)
                )
            elif conv[0] != employee_id:
                raise AtlasError(ErrorCode.UNAUTHORIZED, "conversation belongs to another employee")
            row = self.conn.execute(
                "SELECT * FROM request_receipts WHERE employee_id = ? AND operation = ? AND request_key = ?",
                (employee_id, SEND, key),
            ).fetchone()
            if row is not None:
                if row["payload_hash"] not in (digest, "legacy"):
                    raise AtlasError(
                        ErrorCode.VERSION_CONFLICT,
                        "this request id was already used with different content",
                        recommended_action="send the new content with a new request id",
                    )
                decision = json.loads(row["decision_json"]) if row["decision_json"] else None
                if row["state"] == "COMPLETED":
                    return Receipt(key, "COMPLETED", row["message_id"], json.loads(row["result_json"]), decision)
                if row["state"] == "PROCESSING" and parse_utc(row["lease_expires_at"]) > now_dt:
                    return Receipt(key, "PROCESSING", row["message_id"], decision=decision, busy=True)
                if claim:  # RECEIVED, or PROCESSING whose processor died: resume it
                    self.conn.execute(
                        "UPDATE request_receipts SET state = 'PROCESSING', lease_expires_at = ?, updated_at = ?"
                        " WHERE employee_id = ? AND operation = ? AND request_key = ?",
                        (lease, now, employee_id, SEND, key),
                    )
                return Receipt(key, "PROCESSING" if claim else row["state"], row["message_id"], decision=decision)
            if p.get("intent") == "delegate" and p.get("reply_to_message_id"):
                target = self.conn.execute(
                    "SELECT id, role, conversation_id FROM messages WHERE id = ?", (p["reply_to_message_id"],)
                ).fetchone()
                if target is None or target["conversation_id"] != cid or target["role"] != "owner":
                    # A3-26: only an owner message of THIS conversation (hence this employee) is delegated
                    raise AtlasError(ErrorCode.INVALID_INPUT, "only an owner message of this conversation can be delegated")
                mid = str(target["id"])  # no second owner message is stored
            else:
                origin = "local_app" if actor.channel == "local_app" else "paired_device"
                mid = self.post_in_txn(
                    cid,
                    role="owner",
                    kind="chat",
                    content=p["text"],
                    origin=origin,
                    client_message_id=key,
                    classification=classify_owner_text(p["text"]),
                )
                for aid in dict.fromkeys(p.get("artifact_ids", [])):  # A3-15: kept with the message
                    art = self.conn.execute("SELECT employee_id FROM artifacts WHERE id = ?", (aid,)).fetchone()
                    if art is None or art[0] != employee_id:
                        raise AtlasError(ErrorCode.INVALID_INPUT, "attachment not found for this employee")
                    self.conn.execute(
                        "INSERT OR IGNORE INTO message_attachments(message_id, artifact_id) VALUES (?,?)", (mid, aid)
                    )
            self.conn.execute(
                "INSERT INTO request_receipts(employee_id, operation, request_key, payload_hash, state, message_id,"
                " lease_expires_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (employee_id, SEND, key, digest, "PROCESSING" if claim else "RECEIVED", mid,
                 lease if claim else None, now, now),
            )
        return Receipt(key, "PROCESSING" if claim else "RECEIVED", mid)

    def _release(self, employee_id: str, key: str) -> None:
        """The processor failed: the request stays received and is resumed by the next resend."""
        try:
            with transaction(self.conn):
                self.conn.execute(
                    "UPDATE request_receipts SET state = 'RECEIVED', lease_expires_at = NULL, updated_at = ?"
                    " WHERE employee_id = ? AND operation = ? AND request_key = ? AND state = 'PROCESSING'",
                    (to_utc_str(self.clock.now()), employee_id, SEND, key),
                )
        except (sqlite3.Error, AtlasError):
            pass

    def recover_receipts(self) -> int:
        """After a restart nobody is processing anything: PROCESSING receipts become resumable."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE request_receipts SET state = 'RECEIVED', lease_expires_at = NULL, updated_at = ?"
                " WHERE state = 'PROCESSING'",
                (to_utc_str(self.clock.now()),),
            )
        return int(cur.rowcount)

    def _from_receipt(self, rec: Receipt) -> dict[str, Any]:
        r = rec.result or {}
        reply_id = r.get("reply_id")
        return {
            "message": self.get_message(rec.message_id),
            "reply": self.get_message(reply_id) if reply_id else None,
            "intent": r.get("intent", "duplicate"),
            "task_id": r.get("task_id"),
            "duplicate": True,
            **(r.get("extra") or {}),
        }

    def _remember_decision(self, decision: dict[str, Any]) -> None:
        """Persist a billed model decision before acting on it, so a resend never pays twice."""
        if self._active is None:
            return
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE request_receipts SET decision_json = ?, updated_at = ?"
                " WHERE employee_id = ? AND operation = ? AND request_key = ?",
                (json.dumps(decision), to_utc_str(self.clock.now()), self._active[0], SEND, self._active[1]),
            )

    def handle(self, actor: Actor, employee_id: str, p: dict[str, Any]) -> dict[str, Any]:
        rec = self.receive(actor, employee_id, p, claim=True)
        if rec.result is not None:  # idempotent resend of a completed request: same result, nothing twice
            return self._from_receipt(rec)
        if rec.busy:
            return {
                "message": self.get_message(rec.message_id),
                "reply": None,
                "intent": "processing",
                "task_id": None,
                "duplicate": True,
                "receipt_state": "PROCESSING",
            }
        self._active, self._decision = (employee_id, rec.key), rec.decision
        try:
            return self._route(actor, employee_id, p, rec.message_id)
        except BaseException:
            self._release(employee_id, rec.key)
            raise
        finally:
            self._active, self._decision = None, None

    def _route(self, actor: Actor, employee_id: str, p: dict[str, Any], mid: str) -> dict[str, Any]:
        """Intent routing (spec 7.1). Deterministic for exact controls and explicit targets; general
        language never lets a keyword, an attachment or a pending question decide on its own."""
        cid = p["conversation_id"]
        text: str = p["text"]
        norm = normalize(text)
        intent = p.get("intent", "auto")
        attachments: list[str] = list(dict.fromkeys(p.get("artifact_ids", [])))

        # Explicit delegation of an earlier owner message (no second owner message is stored).
        if intent == "delegate" and p.get("reply_to_message_id"):
            target = self.get_message(mid)
            return self._delegate(
                actor,
                employee_id,
                cid,
                target["message_id"],
                target["content"],
                attachments + [a for a in self._attachments_of(mid) if a not in attachments],
                existing_message=True,
            )

        marker = f"reply:{mid}"

        if norm in STOP_WORDS:
            rep = self.tasks.stop_all(actor=actor, employee_id=employee_id)
            for tid in rep.paused_tasks:
                self.broker.request_cancel(tid)
            self._set_kind(mid, "control")
            parts = [
                f"Parei: {len(rep.paused_tasks)} tarefa(s) pausada(s) e nenhum passo novo será iniciado."
            ]
            if rep.in_flight_actions:
                parts.append(
                    f"{len(rep.in_flight_actions)} ação(ões) já estavam em andamento; pedi a interrupção, "
                    "mas o que já foi enviado não pode ser desfeito."
                )
            if rep.unknown_actions:
                parts.append(
                    f"{len(rep.unknown_actions)} ação(ões) têm resultado incerto e serão conferidas "
                    "antes de qualquer repetição."
                )
            reply = self.say(cid, "control", " ".join(parts), reply_marker=marker)
            return self._result(mid, reply, "control", None, paused=rep.paused_tasks)

        if intent == "delegate":
            return self._delegate(actor, employee_id, cid, mid, text, attachments, marker=marker)

        # ANSWER_QUESTION with an explicit target (the "Responder" action): never guessed (A3-14).
        if p.get("reply_to_message_id"):
            q = self.conn.execute(
                f"SELECT {MSG} FROM messages m WHERE m.id = ? AND m.conversation_id = ? AND m.kind = 'question'",  # noqa: S608 - MSG is a constant column list
                (p["reply_to_message_id"], cid),
            ).fetchone()
            if q is not None:
                if not self._question_open(q["id"], q["task_id"]):
                    self._set_kind(mid, "answer", q["task_id"])
                    reply = self.say(
                        cid,
                        "error",
                        "Essa pergunta já foi respondida ou a tarefa não está mais aguardando você; "
                        "nada foi alterado.",
                        task_id=q["task_id"],
                        reply_marker=marker,
                    )
                    return self._result(mid, reply, "answer_rejected", q["task_id"])
                return self._answer(actor, mid, self._message(q), cid, marker)

        if attachments and not p.get("task_id") and _STORE_ONLY.search(norm):
            return self._share_only(mid, cid, attachments, marker)

        m = _MEMORY.match(text)
        if m and not attachments:
            return self._remember(actor, employee_id, mid, m.group("c").strip(), cid, marker)

        if _STATUS.search(norm):
            self._set_kind(mid, "status")
            return self._result(
                mid,
                self.say(cid, "status", self._status_text(employee_id), reply_marker=marker),
                "status",
                None,
            )

        if p.get("task_id") or _CORRECTION.match(norm):
            if attachments and p.get("task_id"):
                return self._attach_to_task(actor, employee_id, cid, mid, text, p["task_id"], attachments, marker)
            handled = self._correct(actor, employee_id, cid, mid, text, p.get("task_id"), marker)
            if handled is not None:
                return handled

        # ANSWER_QUESTION inferred only when unambiguous (A3-14): a short continuation right after the
        # single open question. Status, memory, new requests and questions are never consumed.
        pending = self._pending_questions(cid)
        if pending and self._looks_like_answer(norm, text):
            last_employee = self.conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND role = 'employee' ORDER BY rowid DESC LIMIT 1",
                (cid,),
            ).fetchone()
            if len(pending) == 1 and (
                (last_employee is not None and last_employee[0] == pending[0]["message_id"])
                or self._names_an_option(norm, pending[0]["content"])
            ):
                return self._answer(actor, mid, pending[0], cid, marker)
            self._set_kind(mid, "answer")
            titles = "\n".join(f"• {q['objective'][:80]}: «{q['content'][:80]}»" for q in pending[:5])
            reply = self.say(
                cid,
                "question",
                "Você está respondendo a qual pergunta? Não retomei nenhuma tarefa ainda.\n"
                + titles
                + "\nUse «Responder» na pergunta certa.",
                reply_marker=marker,
            )
            return self._result(mid, reply, "answer_ambiguous", None)

        return self._chat(actor, employee_id, cid, mid, text, attachments, marker)

    def _attachments_of(self, mid: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT artifact_id FROM message_attachments WHERE message_id = ? ORDER BY rowid", (mid,)
            )
        ]

    def _question_open(self, question_id: str, task_id: str | None) -> bool:
        if task_id is None:
            return False
        task = self.conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
        answered = self.conn.execute(
            "SELECT 1 FROM messages a JOIN messages q ON q.id = ? WHERE a.task_id = q.task_id AND a.kind = 'answer'"
            " AND a.role = 'owner' AND a.rowid > q.rowid",
            (question_id,),
        ).fetchone()
        return task is not None and task[0] == "WAITING_USER" and answered is None

    def _pending_questions(self, cid: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f"SELECT {MSG}, t.objective FROM messages m JOIN tasks t ON t.id = m.task_id WHERE m.conversation_id = ?"  # noqa: S608 - MSG is a constant column list
            " AND m.kind = 'question' AND t.state = 'WAITING_USER' AND NOT EXISTS (SELECT 1 FROM messages a"
            " WHERE a.task_id = m.task_id AND a.kind = 'answer' AND a.role = 'owner' AND a.rowid > m.rowid)"
            " ORDER BY m.rowid",
            (cid,),
        ).fetchall()
        return [{**self._message(r), "objective": r["objective"]} for r in rows]

    @staticmethod
    def _names_an_option(norm: str, question: str) -> bool:
        """The short reply repeats a significant word of the question (e.g. "planilha" for "PDF ou
        planilha?"), which makes the continuation unambiguous even after other exchanges."""
        asked = set(normalize(question).replace("?", " ").replace(":", " ").replace(",", " ").split())
        return any(len(w) >= 3 and w in asked for w in norm.split())

    @staticmethod
    def _looks_like_answer(norm: str, text: str) -> bool:
        words = norm.split()
        return (
            0 < len(words) <= 12
            and len(text) <= 120
            and not text.rstrip().endswith("?")
            and not _REQUEST_START.match(norm)
            and not _MEMORY.match(text)
        )

    def _share_only(self, mid: str, cid: str, attachments: list[str], marker: str) -> dict[str, Any]:
        """SHARE_ONLY (A3-15): keep the files with the message; no task, no analysis, nothing sent."""
        names = [
            str(self.conn.execute("SELECT name FROM artifacts WHERE id = ?", (aid,)).fetchone()[0])
            for aid in attachments
        ]
        reply = self.say(
            cid,
            "ack",
            f"Guardei {len(attachments)} arquivo(s): {', '.join(names)[:300]}. Não criei tarefa; quando quiser "
            "que eu trabalhe neles, é só pedir.",
            reply_marker=marker,
        )
        return self._result(mid, reply, "share_only", None)

    def _attach_to_task(
        self,
        actor: Actor,
        employee_id: str,
        cid: str,
        mid: str,
        text: str,
        task_id: str,
        attachments: list[str],
        marker: str,
    ) -> dict[str, Any]:
        """ATTACH_TO_TASK (A3-15): the files become inputs of THAT task and a new instruction revision."""
        row = self.conn.execute(
            "SELECT objective, employee_id, state FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None or row["employee_id"] != employee_id:
            raise AtlasError(ErrorCode.INVALID_INPUT, "task not found for this employee")
        prior = self.conn.execute(
            "SELECT revision FROM task_instruction_versions WHERE task_id = ? AND source_message_id = ?",
            (task_id, mid),
        ).fetchone()
        if prior is None:
            with transaction(self.conn):
                for aid in attachments:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO artifact_links(artifact_id, task_id, relation) VALUES (?,?,'input')",
                        (aid, task_id),
                    )
            rev = self.tasks.update_instruction(
                task_id,
                actor=actor,
                text=f"{text}\n[anexos: {', '.join(attachments)}]",
                kind="ATTACHMENT",
                source_message_id=mid,
            )
        else:
            rev = int(prior[0])
        self._set_kind(mid, "correction", task_id)
        reply = self.say(
            cid,
            "ack",
            f"Anexei {len(attachments)} arquivo(s) à tarefa «{row['objective'][:120]}» (revisão {rev} das "
            "instruções). O próximo passo já considera esse material.",
            task_id=task_id,
            reply_marker=marker,
        )
        return self._result(mid, reply, "attach_to_task", task_id, instruction_revision=rev)

    # ------------------------------------------------------------------ intents

    def _correct(
        self,
        actor: Actor,
        employee_id: str,
        cid: str,
        mid: str,
        text: str,
        target: str | None,
        marker: str,
    ) -> dict[str, Any] | None:
        """CORRECT_TASK (A3-03, spec 6.3/7.2): explicit target first; infer only when unambiguous."""
        if target:
            row = self.conn.execute(
                "SELECT id, objective, employee_id, state FROM tasks WHERE id = ?", (target,)
            ).fetchone()
            if row is None or row["employee_id"] != employee_id:
                raise AtlasError(ErrorCode.INVALID_INPUT, "task not found for this employee")
            candidates = [row] if row["state"] not in ("COMPLETED", "FAILED", "CANCELLED") else []
            if not candidates:
                reply = self.say(
                    cid,
                    "error",
                    f"A tarefa «{row['objective'][:120]}» já terminou ({row['state']}); a correção não foi "
                    "aplicada. Se quiser, delegue um novo pedido com a mudança.",
                    reply_marker=marker,
                )
                self._set_kind(mid, "correction", row["id"])
                return self._result(mid, reply, "correction_rejected", row["id"])
        else:
            candidates = self.conn.execute(
                "SELECT id, objective FROM tasks WHERE conversation_id = ? AND state NOT IN"
                " ('COMPLETED','FAILED','CANCELLED') ORDER BY created_at DESC",
                (cid,),
            ).fetchall()
            if not candidates:
                return None  # nothing to correct: treat as ordinary conversation
        if len(candidates) > 1:
            self._set_kind(mid, "correction")
            titles = "\n".join(f"• {c['objective'][:80]}" for c in candidates[:5])
            reply = self.say(
                cid,
                "question",
                "Essa mudança vale para qual trabalho? Não alterei nenhum ainda.\n"
                + titles
                + "\nUse «Responder nesta tarefa» no trabalho certo e reenvie a correção.",
                reply_marker=marker,
            )
            return self._result(mid, reply, "correction_ambiguous", None)
        task_id = str(candidates[0]["id"])
        prior = self.conn.execute(
            "SELECT revision FROM task_instruction_versions WHERE task_id = ? AND source_message_id = ?",
            (task_id, mid),
        ).fetchone()
        rev = (
            int(prior[0])  # resumed request: this correction was already recorded
            if prior is not None
            else self.tasks.update_instruction(
                task_id, actor=actor, text=text, kind="CORRECTION", source_message_id=mid
            )
        )  # durable before any acknowledgement
        self._set_kind(mid, "correction", task_id)
        done = self.conn.execute(
            "SELECT COUNT(*) FROM actions WHERE task_id = ? AND status = 'CONFIRMED'"
            " AND effect_class IN ('EXTERNAL_WRITE','IRREVERSIBLE')",
            (task_id,),
        ).fetchone()[0]
        note = (
            f" Antes da correção já tinham ocorrido {done} ação(ões) externa(s); elas não são desfeitas."
            if done
            else ""
        )
        reply = self.say(
            cid,
            "ack",
            f"Registrei a correção na tarefa «{candidates[0]['objective'][:120]}» (revisão {rev} das "
            "instruções). O próximo passo já segue essa instrução e propostas anteriores ainda não "
            "executadas foram descartadas." + note,
            task_id=task_id,
            reply_marker=marker,
        )
        return self._result(mid, reply, "correction", task_id, instruction_revision=rev)

    def _result(
        self, mid: str, reply: dict[str, Any] | None, intent: str, task_id: str | None, **extra: Any
    ) -> dict[str, Any]:
        if self._active is not None:
            with transaction(self.conn):
                self.conn.execute(
                    "UPDATE request_receipts SET state = 'COMPLETED', lease_expires_at = NULL, result_json = ?,"
                    " updated_at = ? WHERE employee_id = ? AND operation = ? AND request_key = ?",
                    (
                        json.dumps(
                            {
                                "intent": intent,
                                "task_id": task_id,
                                "reply_id": reply["message_id"] if reply else None,
                                "extra": extra,
                            }
                        ),
                        to_utc_str(self.clock.now()),
                        self._active[0],
                        SEND,
                        self._active[1],
                    ),
                )
        return {
            "message": self.get_message(mid),
            "reply": reply,
            "intent": intent,
            "task_id": task_id,
            "duplicate": False,
            **extra,
        }

    def _set_kind(self, mid: str, kind: str, task_id: str | None = None) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE messages SET kind = ?, task_id = COALESCE(?, task_id) WHERE id = ?",
                (kind, task_id, mid),
            )

    def _status_text(self, employee_id: str) -> str:
        rows = self.conn.execute(
            "SELECT objective, state, blocked_reason FROM tasks WHERE employee_id = ? AND state NOT IN"
            " ('COMPLETED','FAILED','CANCELLED') ORDER BY updated_at DESC LIMIT 5",
            (employee_id,),
        ).fetchall()
        done = self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE employee_id = ? AND state = 'COMPLETED'", (employee_id,)
        ).fetchone()[0]
        if not rows:
            return f"Não há trabalho em andamento. Tarefas concluídas até agora: {done}."
        labels = {
            "CREATED": "na fila",
            "READY": "na fila",
            "RUNNING": "em execução",
            "WAITING_USER": "aguardando você",
            "WAITING_APPROVAL": "aguardando aprovação",
            "BLOCKED": "bloqueada",
            "PAUSED": "pausada",
            "RETRYING": "nova tentativa agendada",
            "VERIFYING": "verificando o resultado",
        }
        reasons = {
            "EXTERNAL_EFFECT_UNKNOWN": "resultado de uma ação incerto",
            "BUDGET_EXCEEDED": "orçamento esgotado",
            "PROVIDER_UNAVAILABLE": "serviço de inteligência indisponível",
            "WORKSPACE_OFFLINE": "ambiente de trabalho indisponível",
            "HUMAN_INTERVENTION_REQUIRED": "precisa de você",
            "RETRY_LIMIT": "tentativas esgotadas",
            "NO_PROGRESS": "sem progresso",
        }
        lines = [
            f"• {r[0][:80]} — {labels.get(r[1], r[1])}" + (f" ({reasons.get(r[2], r[2])})" if r[2] else "")
            for r in rows
        ]
        return "Trabalho em andamento:\n" + "\n".join(lines) + f"\nConcluídas: {done}."

    def _answer(
        self, actor: Actor, mid: str, question: dict[str, Any], cid: str, marker: str
    ) -> dict[str, Any]:
        tid = question["task_id"]
        self._set_kind(mid, "answer", tid)
        task = self.tasks.get(tid)
        if task["state"] == TaskState.WAITING_USER:
            self.tasks.transition(
                tid,
                TaskState.READY,
                expected_version=task["version"],
                actor=actor,
                reason="owner answered the question",
            )
        reply = self.say(
            cid,
            "ack",
            f"Obrigado. Vou retomar «{task['objective'][:120]}» com a sua resposta.",
            task_id=tid,
            reply_marker=marker,
        )
        return self._result(mid, reply, "answer", tid)

    def _remember(
        self, actor: Actor, employee_id: str, mid: str, content: str, cid: str, marker: str
    ) -> dict[str, Any]:
        prior = self.conn.execute(
            "SELECT m.id FROM memories m JOIN memory_versions v ON v.memory_id = m.id AND v.version = 1"
            " JOIN sources s ON s.id = v.source_id WHERE s.ref = ? AND m.employee_id = ?",
            (f"message:{mid}", employee_id),
        ).fetchone()
        if prior is not None:  # resumed request: the proposal already exists, reuse it
            return self._memory_reply(mid, cid, marker, str(prior[0]))
        src = self.memory.add_source(
            actor=actor, kind="owner_message", ref=f"message:{mid}", employee_id=employee_id
        )
        kind = "PREFERENCE" if re.search(r"prefir|prefer|gosto|quero", normalize(content)) else "FACT"
        sensitivity = "SENSITIVE" if _SENSITIVE.search(normalize(content)) else "INTERNAL"
        try:
            memory_id = self.memory.propose(
                actor=actor,
                employee_id=employee_id,
                type=kind,
                content=content,
                source_id=src,
                sensitivity=sensitivity,
                require_confirmation=True,
            )
        except AtlasError as exc:
            self._set_kind(mid, "memory")
            reply = self.say(cid, "error", f"Não vou guardar isso: {exc.message}", reply_marker=marker)
            return self._result(mid, reply, "memory", None)
        return self._memory_reply(mid, cid, marker, memory_id)

    def _memory_reply(self, mid: str, cid: str, marker: str, memory_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT m.type, m.sensitivity, v.content FROM memories m JOIN memory_versions v"
            " ON v.memory_id = m.id AND v.version = m.current_version WHERE m.id = ?",
            (memory_id,),
        ).fetchone()
        kind, sensitivity, content = row[0], row[1], row[2]
        self._set_kind(mid, "memory")
        with transaction(self.conn):  # the request and its echo carry the memory's protection (A3-02)
            self.conn.execute(
                "UPDATE messages SET classification = ? WHERE id = ? AND classification <> 'SENSITIVE'",
                (sensitivity if sensitivity != "PUBLIC" else "INTERNAL", mid),
            )
        note = (
            " Por ser uma informação sensível, ela ficará restrita e poderá ser excluída a qualquer momento."
            if sensitivity == "SENSITIVE"
            else ""
        )
        reply = self.say(
            cid,
            "memory",
            f"Posso guardar como {'preferência' if kind == 'PREFERENCE' else 'fato'}: "
            f"«{content}». Confirme para guardar; você pode corrigir ou excluir depois.{note}",
            memory_id=memory_id,
            reply_marker=marker,
            classification=sensitivity if sensitivity != "PUBLIC" else "INTERNAL",
        )
        return self._result(mid, reply, "memory", None, memory_id=memory_id)

    def _delegate(
        self,
        actor: Actor,
        employee_id: str,
        cid: str,
        mid: str,
        objective: str,
        artifact_ids: list[str],
        *,
        existing_message: bool = False,
        marker: str | None = None,
    ) -> dict[str, Any]:
        for aid in artifact_ids:
            row = self.conn.execute("SELECT employee_id FROM artifacts WHERE id = ?", (aid,)).fetchone()
            if row is None or row[0] != employee_id:
                raise AtlasError(ErrorCode.INVALID_INPUT, "attachment not found for this employee")
        tid = self.tasks.create(
            actor,
            employee_id=employee_id,
            objective=objective[:4000],
            criteria=[("Resultado entregue e verificado", True)],
            conversation_id=cid,
            client_request_id=mid,
            original_request=objective,
            source_message_id=mid,
            data_policy=self._message_classification(mid),
            input_artifact_ids=artifact_ids,  # linked in the same commit as the task (A3-12)
        )
        # Delegating an earlier message keeps its first reply (e.g. "not configured") and adds the ack.
        marker = f"reply:{mid}:delegated" if existing_message else (marker or f"reply:{mid}")
        n = len(artifact_ids)
        reply = self.say(
            cid,
            "ack",
            f"Criei a tarefa: «{objective[:160]}»"
            + (f" com {n} anexo(s)" if n else "")
            + ". Vou avisar aqui quando houver resultado ou dúvida.",
            task_id=tid,
            reply_marker=marker,
        )
        return self._result(mid, reply, "delegate", tid)

    def _message_classification(self, mid: str) -> str:
        row = self.conn.execute("SELECT classification FROM messages WHERE id = ?", (mid,)).fetchone()
        return str(row[0]) if row else "INTERNAL"

    def _chat(
        self,
        actor: Actor,
        employee_id: str,
        cid: str,
        mid: str,
        text: str,
        artifact_ids: list[str],
        marker: str,
    ) -> dict[str, Any]:
        status = self.intelligence.status() if self.intelligence else None
        if status is None or not status.configured:
            reason = status.reason if status else "inteligência não carregada"
            kept = f"Recebi e guardei {len(artifact_ids)} arquivo(s). " if artifact_ids else ""
            reply = self.say(
                cid,
                "error",
                kept + "Ainda não consigo conversar livremente: " + reason + ". Se quiser que eu "
                "trabalhe nisso, use «Delegar como tarefa».",
                reply_marker=marker,
            )
            return self._result(mid, reply, "chat_unavailable", None)
        assert self.intelligence is not None
        if self._decision is not None:  # resumed after a billed decision: act on it, do not call again
            return self._act_on_chat(actor, employee_id, cid, mid, text, artifact_ids, marker, self._decision)
        history = self.history(cid, employee_id, None, 20)["messages"]
        items = [
            ContextItem(
                Authority.POLICY,
                "You are chatting with your owner. Decide if the latest message asks "
                "you to DO work (intent=delegate, objective=short task statement) or is conversation "
                "(intent=chat, reply=your answer in Portuguese). Never claim to have started work; "
                "the system creates tasks, not you.",
                "policy",
                required=True,
            )
        ]
        excluded = {
            r[0]
            for r in self.conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND context_excluded = 1", (cid,)
            )
        }  # forgotten or 'do not use' content never reaches a model (A3-17)
        for msg in history:
            if msg["message_id"] == mid or msg["message_id"] in excluded:
                continue
            who = "owner" if msg["role"] == "owner" else "atlas (earlier reply, may be wrong)"
            items.append(  # earlier turns are context, never instructions or verified facts (A3-18)
                ContextItem(
                    Authority.CONVERSATION,
                    f"{who}: {msg['content']}",
                    f"message:{msg['message_id']}",
                    msg["classification"],
                )
            )
        items.append(
            ContextItem(
                Authority.OWNER_INSTRUCTION,
                text,
                f"message:{mid}",
                self._message_classification(mid),
                required=True,
            )
        )
        # A3-01: durable knowledge, not only the last messages (same service as tasks).
        for k in KnowledgeContextService(self.conn, self.clock).context_for(employee_id, text):
            items.append(
                ContextItem(Authority.OWNER_MEMORY, k.render(), f"memory:{k.hit.memory_id}", k.hit.sensitivity)
            )
        guard = EgressGuard(self.conn)
        try:
            built = ContextBuilder().build(items, max_classification=guard.max_allowed("openai", "conversation"))
        except RequiredContextWithheld:
            reply = self.say(
                cid,
                "error",
                "Sua mensagem parece conter um dado sensível (saúde, documento pessoal, dados de crianças, "
                "finanças…). Sem a sua autorização eu não envio isso ao provedor de IA. Você pode autorizar "
                "esse uso em Configurações › Privacidade, reescrever sem o dado ou pedir que eu apenas guarde "
                "a informação. Nada foi enviado.",
                reply_marker=marker,
            )
            return self._result(mid, reply, "chat_blocked_sensitive", None)
        except ContextOverflow:
            reply = self.say(
                cid,
                "error",
                "Sua mensagem é longa demais para eu responder de uma vez. Divida em partes ou use "
                "«Delegar como tarefa» para eu trabalhar nela por etapas. Nada foi enviado ao modelo.",
                reply_marker=marker,
            )
            return self._result(mid, reply, "chat_error", None)
        try:
            resp = self.intelligence.build_client().call(
                task_id=None,
                employee_id=employee_id,
                purpose="conversation",
                req=Requirements(structured_output=True, data_classification=built.classification),
                request=ModelRequest(
                    "auto",
                    built.messages,
                    max_output_tokens=800,
                    json_schema=CHAT_SCHEMA,
                    classification=built.classification,
                ),
            )
            decision = json.loads(resp.output_text)
            if next(_CHAT_VALIDATOR.iter_errors(decision), None) is not None:  # full contract (A3-06)
                raise ValueError("chat decision violates its schema")
        except (AtlasError, ValueError) as exc:
            msg = exc.message if isinstance(exc, AtlasError) else "resposta do modelo inválida"
            reply = self.say(
                cid,
                "error",
                f"Não consegui responder agora ({msg}). Nada foi executado.",
                reply_marker=marker,
            )
            return self._result(mid, reply, "chat_error", None)
        self._remember_decision(decision)
        return self._act_on_chat(actor, employee_id, cid, mid, text, artifact_ids, marker, decision)

    def _act_on_chat(
        self,
        actor: Actor,
        employee_id: str,
        cid: str,
        mid: str,
        text: str,
        artifact_ids: list[str],
        marker: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        if decision["intent"] == "delegate":
            objective = decision["objective"].strip() or text
            return self._delegate(actor, employee_id, cid, mid, objective, artifact_ids, marker=marker)
        if not decision["reply"].strip():
            reply = self.say(
                cid, "error", "Não consegui responder agora (resposta vazia). Nada foi executado.",
                reply_marker=marker,
            )
            return self._result(mid, reply, "chat_error", None)
        reply = self.say(cid, "chat", decision["reply"].strip(), reply_marker=marker)
        return self._result(mid, reply, "chat", None)
