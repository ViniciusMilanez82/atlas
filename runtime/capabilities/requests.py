"""Capability requests (N18, spec 1.3, 16.5; scenario T36 - the part that needs no external account).

When the employee finds a missing capability it does not improvise: it files a concrete request - the
problem, what is missing, the provider, evidence that it solves the problem, the price observed with
currency and renewal, which data classes would be sent, free alternatives, risk and a test plan. The
owner decides. Approving a subscription is NOT consent to send sensitive data to it (that stays with the
Egress Guard) and does not execute any purchase: purchases need a homologated driver and their own exact
approval. A rejection lets the task continue with an alternative or deliver the limitation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any

from runtime.notifications.outbox import enqueue_in_txn
from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from shared.actors import Actor
from shared.canonical import canonical_hash
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

RECURRENCES = ("once", "monthly", "yearly")
QUOTE_VALIDITY = timedelta(days=7)  # an observed price older than this must be quoted again (R5-09)


def render(req: dict[str, Any]) -> str:
    price = req["price"]
    renew = {"once": "pagamento único", "monthly": "renovação mensal", "yearly": "renovação anual"}[
        price["recurrence"]
    ]
    alts = "; ".join(req["alternatives"]) or "nenhuma encontrada"
    return (
        f"Para continuar preciso de um recurso que não tenho: {req['missing_capability']}.\n"
        f"Problema: {req['problem']}\n"
        f"Serviço proposto: {req['provider']} — {req['evidence']}\n"
        f"Preço observado: {price['amount']} {price['currency']} ({renew}); fonte: {price['source']}\n"
        f"Dados que seriam enviados: {', '.join(req['data_shared']) or 'nenhum'}\n"
        f"Alternativas: {alts}\n"
        f"Risco: {req['risk']}\nComo eu testaria antes de usar: {req['test_plan']}\n"
        "Aprovar a assinatura não autoriza compartilhar dados sensíveis nem faz nenhuma compra por si só."
    )


class CapabilityRequests:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock
        self.tasks = TaskEngine(conn, clock)

    def file(self, *, task_id: str, worker: Actor, request: dict[str, Any]) -> str:
        """Record the request and put the task in WAITING_USER with the concrete question (one commit)."""
        if request["price"]["recurrence"] not in RECURRENCES:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown recurrence")
        rid = new_id()
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            task = self.tasks._row(task_id)
            # new conditions (price, provider...) supersede a pending request of the same task: the owner
            # never approves terms that are no longer the ones on the table (R5-09)
            self.conn.execute(
                "UPDATE capability_requests SET status = 'SUPERSEDED', decided_at = ? WHERE task_id = ?"
                " AND status = 'PENDING'",
                (now, task_id),
            )
            self.conn.execute(
                "INSERT INTO capability_requests(id, task_id, employee_id, request_json, status, created_at,"
                " request_sha256) VALUES (?,?,?,?, 'PENDING', ?, ?)",
                (rid, task_id, task["employee_id"], json.dumps(request, ensure_ascii=False), now,
                 canonical_hash(request)),
            )
            if task["state"] == TaskState.RUNNING:
                self.tasks.transition_in_txn(task, TaskState.WAITING_USER, worker, "capability request filed")
            enqueue_in_txn(
                self.conn,
                self.clock,
                employee_id=task["employee_id"],
                task_id=task_id,
                kind="question",
                content=render(request) + f"\n[pedido de recurso {rid}]",
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=task["employee_id"],
                task_id=task_id,
                type="capability.requested",
                actor=worker,
                summary=f"capability request {rid}: {request['missing_capability'][:200]}",
            )
        return rid

    def decide(self, request_id: str, *, actor: Actor, approve: bool, note: str = "") -> dict[str, Any]:
        """Owner decision (R5-09). One local transaction records the decision with the hash of its
        content, the instruction revision that tells the worker, the task's return to the queue and the
        owner notice - or none of them. Resending the SAME decision returns the same result (and completes
        a decision recorded by an older version without its instruction); a DIFFERENT decision for a
        decided request is a conflict. Nothing is bought or disclosed by this decision."""
        status = "APPROVED" if approve else "REJECTED"
        digest = canonical_hash({"request_id": request_id, "status": status, "note": note[:500]})
        now = self.clock.now()
        with transaction(self.conn):
            row = self.conn.execute("SELECT * FROM capability_requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise AtlasError(ErrorCode.INVALID_INPUT, "unknown capability request")
            task = self.tasks._row(row["task_id"])
            if actor.kind != "owner" or actor.id != task["owner_id"]:
                raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner decides capability requests")
            if row["status"] in ("APPROVED", "REJECTED"):
                same = row["decision_sha256"] == digest or (row["decision_sha256"] is None and row["status"] == status)
                if not same:
                    raise AtlasError(
                        ErrorCode.VERSION_CONFLICT,
                        f"request already {row['status']} with a different decision",
                        recommended_action="file a new request if the conditions changed",
                    )
                if row["decision_revision"] is not None:  # idempotent replay: the consolidated result
                    return {"request_id": request_id, "status": row["status"],
                            "instruction_revision": int(row["decision_revision"]), "replayed": True}
                # legacy decision without its local steps: complete them now, in this transaction
            elif row["status"] != "PENDING":
                raise AtlasError(
                    ErrorCode.VERSION_CONFLICT,
                    {"EXPIRED": "the quote expired; the employee must quote again",
                     "SUPERSEDED": "superseded by a request with different conditions",
                     "CANCELLED": "the task ended; nothing to decide"}[row["status"]],
                )
            if task["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
                self.conn.execute(
                    "UPDATE capability_requests SET status = 'CANCELLED', decided_at = ? WHERE id = ?",
                    (to_utc_str(now), request_id),
                )
                return {"request_id": request_id, "status": "CANCELLED", "instruction_revision": None}
            if row["status"] == "PENDING" and parse_utc(row["created_at"]) + QUOTE_VALIDITY <= now:
                self.conn.execute(
                    "UPDATE capability_requests SET status = 'EXPIRED', decided_at = ? WHERE id = ?",
                    (to_utc_str(now), request_id),
                )
                return {"request_id": request_id, "status": "EXPIRED", "instruction_revision": None}
            req = json.loads(row["request_json"])
            rev = self._apply_in_txn(row, req, actor, approve, note)
            self.conn.execute(
                "UPDATE capability_requests SET status = ?, decided_at = ?, decided_by = ?, note = ?,"
                " decision_sha256 = ?, decision_revision = ? WHERE id = ?",
                (status, to_utc_str(now), f"{actor.kind}:{actor.id}", note[:500], digest, rev, request_id),
            )
        return {"request_id": request_id, "status": status, "instruction_revision": rev}

    def _apply_in_txn(
        self, row: sqlite3.Row, req: dict[str, Any], actor: Actor, approve: bool, note: str
    ) -> int:
        status = "APPROVED" if approve else "REJECTED"
        text = (
            f"O proprietário APROVOU contratar {req['provider']} para {req['missing_capability']} "
            f"(até {req['price']['amount']} {req['price']['currency']}, {req['price']['recurrence']}). "
            "Isso não autoriza enviar dados sensíveis nem executa compra: prepare a contratação para aprovação exata."
            if approve
            else f"O proprietário RECUSOU {req['provider']}. Continue com uma alternativa legítima "
            "ou entregue o que for possível explicando a limitação; não insista no mesmo pedido."
        ) + (f" Observação do proprietário: {note}" if note else "")
        rev = self.tasks.update_instruction_in_txn(
            row["task_id"], actor=actor, text=text, kind="ANSWER", material=True, derive=False
        )
        task = self.tasks._row(row["task_id"])
        if task["state"] == TaskState.WAITING_USER:
            self.tasks.transition_in_txn(task, TaskState.READY, actor, f"capability request {status.lower()}")
        enqueue_in_txn(
            self.conn,
            self.clock,
            employee_id=row["employee_id"],
            task_id=row["task_id"],
            kind="status",
            content=(
                f"Registrei sua decisão: {'aprovado' if approve else 'recusado'} — {req['provider']}. "
                + ("Nada foi comprado; a contratação ainda exigirá sua aprovação exata." if approve
                   else "Vou seguir com uma alternativa ou explicar a limitação.")
            ),
        )
        journal.append(
            self.conn,
            self.clock,
            employee_id=row["employee_id"],
            task_id=row["task_id"],
            type="capability.decided",
            actor=actor,
            summary=f"capability request {row['id']} {status.lower()} (instruction revision {rev})",
        )
        return rev

    def pending(self, employee_id: str) -> list[dict[str, Any]]:
        return [
            {
                "request_id": r["id"],
                "task_id": r["task_id"],
                "request": json.loads(r["request_json"]),
                "created_at": r["created_at"],
            }
            for r in self.conn.execute(
                "SELECT * FROM capability_requests WHERE employee_id = ? AND status = 'PENDING' ORDER BY created_at",
                (employee_id,),
            )
        ]
