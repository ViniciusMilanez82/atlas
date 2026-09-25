"""Action Ledger (spec 12.1, 12.2, AT-017.1).

Every external action has its own identity and state, and its intent is persisted before
dispatch. Transitions are guarded (``WHERE status = ?``) so two writers cannot both move it.
UNKNOWN is preserved until reconciliation provides evidence; absence of a confirmation is not
proof of absence of the effect.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage.db import require_transaction

TRANSITIONS: dict[str, frozenset[str]] = {
    "PROPOSED": frozenset({"AUTHORIZED", "CANCELLED_BEFORE_DISPATCH"}),
    "AUTHORIZED": frozenset({"DISPATCHING", "CANCELLED_BEFORE_DISPATCH"}),
    "DISPATCHING": frozenset({"CONFIRMED", "FAILED", "UNKNOWN"}),
    "UNKNOWN": frozenset({"CONFIRMED", "FAILED"}),  # only through reconciliation with evidence
    "CONFIRMED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED_BEFORE_DISPATCH": frozenset(),
}


class Ledger:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def propose_in_txn(
        self,
        *,
        task_id: str,
        step_id: str | None,
        tool_id: str,
        tool_version: str,
        effect_class: str,
        risk_class: str,
        tool_input: dict[str, Any],
        input_hash: str,
        destination: str | None,
        worker_id: str | None,
        instruction_revision: int | None = None,
    ) -> str:
        require_transaction(self.conn)
        action_id = new_id()
        now = to_utc_str(self.clock.now())
        self.conn.execute(
            "INSERT INTO actions(id, task_id, step_id, tool_id, tool_version, effect_class, risk_class, status,"
            " input_json, input_hash, destination, worker_id, created_at, updated_at, instruction_revision)"
            " VALUES (?,?,?,?,?,?,?,'PROPOSED',?,?,?,?,?,?,?)",
            (
                action_id,
                task_id,
                step_id,
                tool_id,
                tool_version,
                effect_class,
                risk_class,
                json.dumps(tool_input, sort_keys=True),
                input_hash,
                destination,
                worker_id,
                now,
                now,
                instruction_revision,
            ),
        )
        return action_id

    def find_open_in_txn(self, task_id: str, input_hash: str) -> sqlite3.Row | None:
        """An identical proposal still waiting (e.g. for approval) is the same action, not a new one."""
        require_transaction(self.conn)
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM actions WHERE task_id = ? AND input_hash = ? AND status = 'PROPOSED'"
            " ORDER BY created_at DESC LIMIT 1",
            (task_id, input_hash),
        ).fetchone()
        return row

    def get(self, action_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown action")
        return row

    def move_in_txn(
        self, action_id: str, src: str, dst: str, reason: str | None = None, **fields: Any
    ) -> None:
        require_transaction(self.conn)
        if dst not in TRANSITIONS[src]:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"invalid ledger transition {src} -> {dst}")
        allowed = {
            "policy_decision",
            "policy_reason",
            "policy_version",
            "fencing_token",
            "idempotency_key",
            "dispatched_at",
            "finished_at",
            "external_reference",
            "approval_id",
            "mandate_id",
            "budget_reservation_id",
        }
        if set(fields) - allowed:
            raise AtlasError(
                ErrorCode.INVALID_INPUT, f"unexpected ledger fields {sorted(set(fields) - allowed)}"
            )
        sets = ["status = ?", "status_reason = COALESCE(?, status_reason)", "updated_at = ?"]
        args: list[Any] = [dst, reason, to_utc_str(self.clock.now())]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            args.append(v)
        args += [action_id, src]
        cur = self.conn.execute(
            f"UPDATE actions SET {', '.join(sets)} WHERE id = ? AND status = ?",  # noqa: S608 - keys whitelisted
            args,
        )
        if cur.rowcount != 1:
            raise AtlasError(ErrorCode.VERSION_CONFLICT, f"action is no longer {src}")

    def annotate_policy_in_txn(self, action_id: str, decision: str, reason: str, version: str) -> None:
        require_transaction(self.conn)
        self.conn.execute(
            "UPDATE actions SET policy_decision = ?, policy_reason = ?, policy_version = ?, updated_at = ?"
            " WHERE id = ?",
            (decision, reason, version, to_utc_str(self.clock.now()), action_id),
        )

    def record_receipt_in_txn(self, action_id: str, external_reference: str, receipt: dict[str, Any]) -> str:
        require_transaction(self.conn)
        rid = new_id()
        self.conn.execute(
            "INSERT INTO external_receipts(id, action_id, external_reference, receipt_json, received_at)"
            " VALUES (?,?,?,?,?)",
            (
                rid,
                action_id,
                external_reference,
                json.dumps(receipt, sort_keys=True),
                to_utc_str(self.clock.now()),
            ),
        )
        return rid
