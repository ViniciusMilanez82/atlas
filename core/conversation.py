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
from typing import Any

from jsonschema import Draft202012Validator

from core.intelligence import IntelligenceSetup
from runtime.memory.manager import MemoryManager
from runtime.models.context import Authority, ContextBuilder, ContextItem
from runtime.models.router import Requirements
from runtime.models.types import ModelRequest
from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from security.broker.broker import Broker
from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

STOP_WORDS = {"pare", "pare tudo", "parar", "stop", "stop all", "pausa tudo", "pause tudo"}
_MEMORY = re.compile(
    r"^\s*(?:por favor,?\s*)?(?:guarde|lembre-se|lembre|memorize|anote)"
    r"(?:\s+(?:esta|essa)\s+(?:preferencia|informacao))?\s*(?:que|:|,)?\s*(?P<c>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_STATUS = re.compile(
    r"\b(status|andamento|progresso|como (?:esta|vai) (?:a|o|as|os)?\s*\w*|o que (?:voce )?(?:esta|anda) fazendo)\b",
    re.IGNORECASE,
)
_CORRECTION = re.compile(r"^\s*(nao era isso|na verdade|corrigindo|correcao|mudei de ideia)\b", re.IGNORECASE)
_SENSITIVE = re.compile(
    r"\b(saude|medic|doenc|cpf|rg|document|filh|crianc|endereco|banco|salario)", re.IGNORECASE
)
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
EMPLOYEE = Actor("runtime", "conversation", "internal")


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
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
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
    ) -> str:
        mid = new_id()
        self.conn.execute(
            "INSERT INTO messages(id, conversation_id, role, origin, client_message_id, content, task_id, kind,"
            " artifact_id, memory_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
    ) -> dict[str, Any]:
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
            )
        return self.get_message(mid)

    def history(
        self, conversation_id: str, employee_id: str, before_message_id: str | None, limit: int
    ) -> dict[str, Any]:
        conv = self.conn.execute(
            "SELECT employee_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if conv is None or conv[0] != employee_id:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "conversation belongs to another employee")
        if before_message_id:
            ref = self.conn.execute(
                "SELECT rowid FROM messages WHERE id = ? AND conversation_id = ?",
                (before_message_id, conversation_id),
            ).fetchone()
            if ref is None:
                raise AtlasError(ErrorCode.INVALID_INPUT, "unknown message in this conversation")
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND rowid < ? ORDER BY rowid DESC LIMIT ?",
                (conversation_id, ref[0], limit + 1),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY rowid DESC LIMIT ?",
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

    def _pending_question(self, conversation_id: str, reply_to: str | None) -> dict[str, Any] | None:
        if reply_to:
            q = self.conn.execute(
                "SELECT * FROM messages WHERE id = ? AND conversation_id = ? AND kind = 'question'",
                (reply_to, conversation_id),
            ).fetchone()
            return self._message(q) if q else None
        rows = self.conn.execute(
            "SELECT m.* FROM messages m JOIN tasks t ON t.id = m.task_id WHERE m.conversation_id = ?"
            " AND m.kind = 'question' AND t.state = 'WAITING_USER' AND NOT EXISTS (SELECT 1 FROM messages a"
            " WHERE a.task_id = m.task_id AND a.kind = 'answer' AND a.rowid > m.rowid) ORDER BY m.rowid",
            (conversation_id,),
        ).fetchall()
        return self._message(rows[0]) if len(rows) == 1 else None

    # ------------------------------------------------------------------ routing

    def handle(self, actor: Actor, employee_id: str, p: dict[str, Any]) -> dict[str, Any]:
        cid = p["conversation_id"]
        conv = self.conn.execute("SELECT employee_id FROM conversations WHERE id = ?", (cid,)).fetchone()
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            if conv is None:
                self.conn.execute(
                    "INSERT INTO conversations(id, employee_id, created_at) VALUES (?,?,?)",
                    (cid, employee_id, now),
                )
            elif conv[0] != employee_id:
                raise AtlasError(ErrorCode.UNAUTHORIZED, "conversation belongs to another employee")
            dup = self.conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND client_message_id = ?",
                (cid, p["client_message_id"]),
            ).fetchone()
        if dup:  # idempotent resend: return what already happened, do nothing twice
            reply = self.conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND client_message_id = ?",
                (cid, f"reply:{dup[0]}"),
            ).fetchone()
            owner_msg = self.get_message(dup[0])
            return {
                "message": owner_msg,
                "reply": self.get_message(reply[0]) if reply else None,
                "intent": "duplicate",
                "task_id": owner_msg["task_id"],
                "duplicate": True,
            }

        text: str = p["text"]
        origin = "local_app" if actor.channel == "local_app" else "paired_device"
        norm = normalize(text)
        intent = p.get("intent", "auto")

        # Explicit delegation of an earlier owner message (no second owner message is stored).
        if intent == "delegate" and p.get("reply_to_message_id"):
            target = self.get_message(p["reply_to_message_id"])
            if target["role"] != "owner":
                raise AtlasError(ErrorCode.INVALID_INPUT, "only an owner message can be delegated")
            return self._delegate(
                actor,
                employee_id,
                cid,
                target["message_id"],
                target["content"],
                p.get("artifact_ids", []),
                existing_message=True,
            )

        with transaction(self.conn):
            mid = self.post_in_txn(
                cid,
                role="owner",
                kind="chat",
                content=text,
                origin=origin,
                client_message_id=p["client_message_id"],
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

        question = None if intent == "delegate" else self._pending_question(cid, p.get("reply_to_message_id"))
        if question is not None:
            return self._answer(actor, mid, question, cid, marker)

        m = _MEMORY.match(text) if intent != "delegate" and _MEMORY.match(norm) else None
        if m:
            return self._remember(actor, employee_id, mid, m.group("c").strip(), cid, marker)

        if intent != "delegate" and _STATUS.search(norm):
            self._set_kind(mid, "status")
            return self._result(
                mid,
                self.say(cid, "status", self._status_text(employee_id), reply_marker=marker),
                "status",
                None,
            )

        if intent != "delegate" and _CORRECTION.match(norm):
            open_task = self.conn.execute(
                "SELECT id, objective FROM tasks WHERE conversation_id = ? AND state NOT IN"
                " ('COMPLETED','FAILED','CANCELLED') ORDER BY created_at DESC LIMIT 1",
                (cid,),
            ).fetchone()
            if open_task:
                with transaction(self.conn):
                    self.conn.execute(
                        "UPDATE messages SET kind = 'correction', task_id = ? WHERE id = ?",
                        (open_task[0], mid),
                    )
                    journal.append(
                        self.conn,
                        self.clock,
                        employee_id=employee_id,
                        task_id=open_task[0],
                        type="task.corrected",
                        actor=actor,
                        summary="owner correction attached",
                    )
                reply = self.say(
                    cid,
                    "ack",
                    f"Anotei a correção na tarefa «{open_task[1][:120]}». Ela será "
                    "considerada no próximo passo.",
                    task_id=open_task[0],
                    reply_marker=marker,
                )
                return self._result(mid, reply, "correction", open_task[0])

        if intent == "delegate":
            return self._delegate(
                actor, employee_id, cid, mid, text, p.get("artifact_ids", []), marker=marker
            )
        return self._chat(actor, employee_id, cid, mid, text, p.get("artifact_ids", []), marker)

    # ------------------------------------------------------------------ intents

    def _result(
        self, mid: str, reply: dict[str, Any] | None, intent: str, task_id: str | None, **extra: Any
    ) -> dict[str, Any]:
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
        src = self.memory.add_source(actor=actor, kind="owner_message", ref=f"message:{mid}")
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
        self._set_kind(mid, "memory")
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
        )
        with transaction(self.conn):
            for aid in artifact_ids:
                self.conn.execute(
                    "INSERT OR IGNORE INTO artifact_links(artifact_id, task_id, relation) VALUES (?,?,'input')",
                    (aid, tid),
                )
            self.conn.execute("UPDATE messages SET task_id = ? WHERE id = ?", (tid, mid))
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
            reply = self.say(
                cid,
                "error",
                "Ainda não consigo conversar livremente: " + reason + ". Se quiser que eu "
                "trabalhe nisso, use «Delegar como tarefa».",
                reply_marker=marker,
            )
            return self._result(mid, reply, "chat_unavailable", None)
        assert self.intelligence is not None
        history = self.history(cid, employee_id, None, 20)["messages"]
        items = [
            ContextItem(
                Authority.POLICY,
                "You are chatting with your owner. Decide if the latest message asks "
                "you to DO work (intent=delegate, objective=short task statement) or is conversation "
                "(intent=chat, reply=your answer in Portuguese). Never claim to have started work; "
                "the system creates tasks, not you.",
                "policy",
            )
        ]
        for msg in history[:-1]:
            auth = Authority.OWNER_INSTRUCTION if msg["role"] == "owner" else Authority.VERIFIED_FACT
            items.append(
                ContextItem(auth, f"{msg['role']}: {msg['content']}", f"message:{msg['message_id']}")
            )
        items.append(ContextItem(Authority.OWNER_INSTRUCTION, text, f"message:{mid}"))
        built = ContextBuilder().build(items)
        try:
            resp = self.intelligence.build_client().call(
                task_id=None,
                employee_id=employee_id,
                purpose="conversation",
                req=Requirements(structured_output=True, data_classification="INTERNAL"),
                request=ModelRequest("auto", built.messages, max_output_tokens=800, json_schema=CHAT_SCHEMA),
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
