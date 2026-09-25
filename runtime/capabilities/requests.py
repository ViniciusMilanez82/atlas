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
from typing import Any

from runtime.notifications.outbox import enqueue_in_txn
from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

RECURRENCES = ("once", "monthly", "yearly")


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
            self.conn.execute(
                "INSERT INTO capability_requests(id, task_id, employee_id, request_json, status, created_at)"
                " VALUES (?,?,?,?, 'PENDING', ?)",
                (rid, task_id, task["employee_id"], json.dumps(request, ensure_ascii=False), now),
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
        """Owner decision. The task resumes with the decision as a new instruction revision; nothing is
        bought or disclosed by this decision."""
        row = self.conn.execute("SELECT * FROM capability_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown capability request")
        if row["status"] != "PENDING":
            raise AtlasError(ErrorCode.VERSION_CONFLICT, f"request already {row['status']}")
        req = json.loads(row["request_json"])
        status = "APPROVED" if approve else "REJECTED"
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE capability_requests SET status = ?, decided_at = ?, decided_by = ?, note = ? WHERE id = ?",
                (status, to_utc_str(self.clock.now()), f"{actor.kind}:{actor.id}", note[:500], request_id),
            )
        text = (
            f"O proprietário APROVOU contratar {req['provider']} para {req['missing_capability']} "
            f"(até {req['price']['amount']} {req['price']['currency']}, {req['price']['recurrence']}). "
            "Isso não autoriza enviar dados sensíveis nem executa compra: prepare a contratação para aprovação exata."
            if approve
            else f"O proprietário RECUSOU {req['provider']}. Continue com uma alternativa legítima "
            "ou entregue o que for possível explicando a limitação; não insista no mesmo pedido."
        ) + (f" Observação do proprietário: {note}" if note else "")
        rev = self.tasks.update_instruction(
            row["task_id"], actor=actor, text=text, kind="ANSWER", material=True
        )
        task = self.tasks.get(row["task_id"])
        if task["state"] == TaskState.WAITING_USER:
            self.tasks.transition(
                row["task_id"],
                TaskState.READY,
                expected_version=task["version"],
                actor=actor,
                reason=f"capability request {status.lower()}",
            )
        return {"request_id": request_id, "status": status, "instruction_revision": rev}

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
