"""Transactional notification outbox (A3-27, spec 5.3; scenario T18).

``enqueue_in_txn`` runs inside the transaction that changes the task state, so "waiting for you",
"done" or "blocked" can never commit without the message that tells the owner. ``OutboxDispatcher``
delivers pending events into the task's conversation; the message insert and the DELIVERED mark share
one transaction and the message carries ``outbox:<event_id>`` as its unique client id, so repeating
delivery (after a crash or by two dispatchers) never shows the same balloon twice. External channels
(e-mail, companion) will add their own receipts; local delivery is exactly-once by construction.
"""

from __future__ import annotations

import sqlite3

from shared.clock import Clock, to_utc_str
from shared.ids import new_id
from storage.db import require_transaction, transaction

KINDS = ("question", "result", "status", "error")
Notice = tuple[str, str, "str | None"]  # (kind, content, artifact_id)


def enqueue_in_txn(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    employee_id: str,
    task_id: str | None,
    kind: str,
    content: str,
    artifact_id: str | None = None,
) -> str:
    require_transaction(conn)
    if kind not in KINDS:
        raise ValueError(f"unknown notification kind {kind}")
    event_id = new_id()
    conn.execute(
        "INSERT INTO notification_outbox(event_id, employee_id, task_id, channel, kind, content, artifact_id,"
        " status, created_at) VALUES (?,?,?,'conversation',?,?,?,'PENDING',?)",
        (event_id, employee_id, task_id, kind, content[:32000], artifact_id, to_utc_str(clock.now())),
    )
    return event_id


class OutboxDispatcher:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def _conversation_in_txn(self, employee_id: str, task_id: str | None) -> str:
        if task_id is not None:
            row = self.conn.execute("SELECT conversation_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is not None and row[0] is not None:
                return str(row[0])
        row = self.conn.execute(
            "SELECT id FROM conversations WHERE employee_id = ? ORDER BY created_at, rowid LIMIT 1",
            (employee_id,),
        ).fetchone()
        if row is not None:
            return str(row[0])
        cid = new_id()  # tasks created outside a conversation still reach the owner's conversation
        self.conn.execute(
            "INSERT INTO conversations(id, employee_id, created_at) VALUES (?,?,?)",
            (cid, employee_id, to_utc_str(self.clock.now())),
        )
        return cid

    def deliver_pending(self, task_id: str | None = None, limit: int = 100) -> int:
        """Deliver pending events (optionally of one task). Returns how many were delivered now."""
        sql = "SELECT * FROM notification_outbox WHERE status = 'PENDING'"
        args: tuple[object, ...] = ()
        if task_id is not None:
            sql += " AND task_id = ?"
            args = (task_id,)
        rows = self.conn.execute(sql + " ORDER BY created_at, rowid LIMIT ?", (*args, limit)).fetchall()
        delivered = 0
        for ev in rows:
            now = to_utc_str(self.clock.now())
            with transaction(self.conn):
                current = self.conn.execute(
                    "SELECT status FROM notification_outbox WHERE event_id = ?", (ev["event_id"],)
                ).fetchone()
                if current is None or current[0] != "PENDING":
                    continue  # another dispatcher got it first
                cid = self._conversation_in_txn(ev["employee_id"], ev["task_id"])
                marker = f"outbox:{ev['event_id']}"
                existing = self.conn.execute(
                    "SELECT id FROM messages WHERE conversation_id = ? AND client_message_id = ?",
                    (cid, marker),
                ).fetchone()
                if existing is not None:
                    mid = str(existing[0])
                else:
                    mid = new_id()
                    self.conn.execute(
                        "INSERT INTO messages(id, conversation_id, role, origin, client_message_id, content, task_id,"
                        " kind, artifact_id, created_at) VALUES (?,?,'employee','system',?,?,?,?,?,?)",
                        (mid, cid, marker, ev["content"], ev["task_id"], ev["kind"], ev["artifact_id"], now),
                    )
                self.conn.execute(
                    "UPDATE notification_outbox SET status = 'DELIVERED', message_id = ?, attempts = attempts + 1,"
                    " delivered_at = ? WHERE event_id = ?",
                    (mid, now, ev["event_id"]),
                )
            delivered += 1
        return delivered
