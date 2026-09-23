"""Approval Engine (spec 11.2, 11.3, AT-008.1).

An approval binds to the canonical hash of the exact parameters. Any material change produces a
different hash and therefore needs a new approval. Decisions come only from the authenticated
owner; R4 requires the local app with strong confirmation. Reservation and consumption happen
atomically inside the broker's dispatch transaction, so replays and races cannot consume twice.
If an effect is UNKNOWN the approval stays held and is never reused blindly.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any

from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.contracts import validate
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id, new_nonce
from shared.money import Money
from storage import journal
from storage.db import require_transaction, transaction

DEFAULT_TTL = timedelta(hours=24)


def _e(code: ErrorCode, msg: str) -> AtlasError:
    return AtlasError(code, msg)


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    d: dict[str, Any] = {
        "schema_version": "1.0",
        "approval_id": r["id"],
        "task_id": r["task_id"],
        "action_id": r["action_id"],
        "requested_by": r["requested_by"],
        "action_type": r["action_type"],
        "destination": r["destination"],
        "params_hash": r["params_hash"],
        "max_cost": (
            {"amount_minor": r["max_cost_minor"], "currency": r["max_cost_currency"]}
            if r["max_cost_currency"]
            else None
        ),
        "recurrence": r["recurrence"],
        "expires_at": r["expires_at"],
        "max_uses": r["max_uses"],
        "uses": r["uses"],
        "policy_version": r["policy_version"],
        "risk_class": r["risk_class"],
        "status": r["status"],
        "created_at": r["created_at"],
        "decided_at": r["decided_at"],
        "decided_by": r["decided_by"],
        "nonce": r["nonce"],
    }
    if r["purchase_json"]:
        d["purchase"] = json.loads(r["purchase_json"])
    return d


class ApprovalEngine:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # ----------------------------------------------------------------- reads

    def get(self, approval_id: str) -> dict[str, Any]:
        r = self.conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if r is None:
            raise _e(ErrorCode.INVALID_INPUT, "unknown approval")
        return _row_to_dict(r)

    def latest_for_action(self, action_id: str) -> dict[str, Any] | None:
        r = self.conn.execute(
            "SELECT * FROM approvals WHERE action_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (action_id,),
        ).fetchone()
        return _row_to_dict(r) if r else None

    # ----------------------------------------------------------------- creation (broker, in txn)

    def request_in_txn(
        self,
        *,
        task_id: str,
        action_id: str,
        employee_id: str,
        action_type: str,
        destination: str,
        params_hash: str,
        max_cost: Money | None,
        risk_class: str,
        policy_version: str,
        purchase: dict[str, Any] | None = None,
        ttl: timedelta = DEFAULT_TTL,
    ) -> dict[str, Any]:
        require_transaction(self.conn)
        now = self.clock.now()
        approval_id = new_id()
        self.conn.execute(
            "INSERT INTO approvals(id, task_id, action_id, requested_by, action_type, destination, params_hash,"
            " max_cost_minor, max_cost_currency, recurrence, expires_at, max_uses, uses, policy_version,"
            " risk_class, status, nonce, purchase_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                approval_id,
                task_id,
                action_id,
                "runtime",
                action_type,
                destination,
                params_hash,
                max_cost.amount_minor if max_cost else None,
                max_cost.currency if max_cost else None,
                "ONCE",
                to_utc_str(now + ttl),
                1,
                0,
                policy_version,
                risk_class,
                "PENDING",
                new_nonce(),
                json.dumps(purchase, sort_keys=True) if purchase else None,
                to_utc_str(now),
            ),
        )
        data = self.get(approval_id)
        validate("approval", data)
        journal.append(
            self.conn,
            self.clock,
            employee_id=employee_id,
            task_id=task_id,
            action_id=action_id,
            type="approval.requested",
            actor=Actor("control_plane", "broker"),
            policy_version=policy_version,
            summary=f"approval requested for {action_type} to {destination} ({risk_class})",
        )
        return data

    # ----------------------------------------------------------------- owner decision

    def decide_in_txn(
        self,
        approval_id: str,
        *,
        actor: Actor,
        approve: bool,
        params_hash: str,
        nonce: str,
    ) -> dict[str, Any]:
        """The owner decides on exactly what was shown (hash + nonce). The LLM never calls this.

        Runs inside the Control Plane transaction that also moves the task out of WAITING_APPROVAL.
        """
        require_transaction(self.conn)
        if actor.kind != "owner" or actor.channel not in ("local_app", "paired_device"):
            raise _e(ErrorCode.UNAUTHORIZED, "only the authenticated owner can decide approvals")
        r = self.conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if r is None:
            raise _e(ErrorCode.INVALID_INPUT, "unknown approval")
        task = self.conn.execute(
            "SELECT owner_id, employee_id FROM tasks WHERE id = ?", (r["task_id"],)
        ).fetchone()
        if task["owner_id"] != actor.id:
            raise _e(ErrorCode.UNAUTHORIZED, "approval belongs to another owner")
        if r["status"] != "PENDING":
            raise _e(ErrorCode.VERSION_CONFLICT, f"approval is {r['status']}, not PENDING")
        if parse_utc(r["expires_at"]) <= self.clock.now():
            self.conn.execute("UPDATE approvals SET status = 'EXPIRED' WHERE id = ?", (approval_id,))
            return self.get(approval_id)
        if params_hash != r["params_hash"] or nonce != r["nonce"]:
            raise _e(ErrorCode.INVALID_INPUT, "decision does not match the approval that was presented")
        if approve and r["risk_class"] == "R4" and not (actor.channel == "local_app" and actor.strong_auth):
            raise _e(ErrorCode.UNAUTHORIZED, "R4 requires strong confirmation in the authenticated local app")
        status = "APPROVED" if approve else "REJECTED"
        self.conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ? WHERE id = ?",
            (status, to_utc_str(self.clock.now()), actor.id, approval_id),
        )
        journal.append(
            self.conn,
            self.clock,
            employee_id=task["employee_id"],
            task_id=r["task_id"],
            action_id=r["action_id"],
            type="approval.decided",
            actor=actor,
            policy_version=r["policy_version"],
            summary=f"{status} via {actor.channel}",
        )
        return self.get(approval_id)

    def revoke(self, approval_id: str, *, actor: Actor) -> None:
        if actor.kind != "owner":
            raise _e(ErrorCode.UNAUTHORIZED, "only the owner can revoke")
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE approvals SET status = 'REVOKED', decided_at = ? WHERE id = ?"
                " AND status IN ('PENDING','APPROVED','RESERVED')",
                (to_utc_str(self.clock.now()), approval_id),
            )
            if cur.rowcount != 1:
                raise _e(ErrorCode.VERSION_CONFLICT, "approval cannot be revoked in its current state")

    # ----------------------------------------------------------------- broker operations (in txn)

    def expire_in_txn(self, approval_id: str) -> None:
        require_transaction(self.conn)
        self.conn.execute(
            "UPDATE approvals SET status = 'EXPIRED' WHERE id = ? AND status IN ('PENDING','APPROVED')",
            (approval_id,),
        )

    def reserve_in_txn(self, approval_id: str, *, action_id: str, params_hash: str) -> None:
        require_transaction(self.conn)
        r = self.conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if r is None:
            raise _e(ErrorCode.APPROVAL_REQUIRED, "unknown approval")
        if r["status"] != "APPROVED":
            raise _e(ErrorCode.APPROVAL_REQUIRED, f"approval is {r['status']}")
        if parse_utc(r["expires_at"]) <= self.clock.now():
            self.conn.execute("UPDATE approvals SET status = 'EXPIRED' WHERE id = ?", (approval_id,))
            raise _e(ErrorCode.APPROVAL_REQUIRED, "approval expired")
        if r["params_hash"] != params_hash or r["action_id"] != action_id:
            raise _e(ErrorCode.APPROVAL_REQUIRED, "parameters changed materially; a new approval is required")
        if r["uses"] >= r["max_uses"]:
            raise _e(ErrorCode.APPROVAL_REQUIRED, "approval has no remaining uses")
        self.conn.execute("UPDATE approvals SET status = 'RESERVED' WHERE id = ?", (approval_id,))
        self.conn.execute(
            "INSERT INTO approval_consumptions(id, approval_id, action_id, status, reserved_at) VALUES (?,?,?,?,?)",
            (new_id(), approval_id, action_id, "RESERVED", to_utc_str(self.clock.now())),
        )

    def _close(self, approval_id: str, action_id: str, status: str) -> sqlite3.Row:
        require_transaction(self.conn)
        cur = self.conn.execute(
            "UPDATE approval_consumptions SET status = ?, closed_at = ? WHERE approval_id = ? AND action_id = ?"
            " AND status IN ('RESERVED','HELD_UNKNOWN')",
            (status, to_utc_str(self.clock.now()), approval_id, action_id),
        )
        if cur.rowcount != 1:
            raise _e(ErrorCode.VERSION_CONFLICT, "no open reservation for this action")
        r: sqlite3.Row = self.conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return r

    def consume_in_txn(self, approval_id: str, *, action_id: str) -> None:
        r = self._close(approval_id, action_id, "CONSUMED")
        uses = r["uses"] + 1
        status = "CONSUMED" if uses >= r["max_uses"] else "APPROVED"
        if r["status"] == "REVOKED":
            status = "REVOKED"
        self.conn.execute(
            "UPDATE approvals SET uses = ?, status = ? WHERE id = ?", (uses, status, approval_id)
        )

    def release_in_txn(self, approval_id: str, *, action_id: str) -> None:
        """Only when it is proven that the effect did not happen."""
        r = self._close(approval_id, action_id, "RELEASED")
        if r["status"] == "RESERVED":
            self.conn.execute("UPDATE approvals SET status = 'APPROVED' WHERE id = ?", (approval_id,))

    def hold_unknown_in_txn(self, approval_id: str, *, action_id: str) -> None:
        """Effect uncertain: keep the approval RESERVED so it can never be reused blindly."""
        require_transaction(self.conn)
        self.conn.execute(
            "UPDATE approval_consumptions SET status = 'HELD_UNKNOWN' WHERE approval_id = ? AND action_id = ?"
            " AND status = 'RESERVED'",
            (approval_id, action_id),
        )
