"""Limited recurring mandates (spec 11.1, AT-008.2).

A mandate lets the owner pre-authorize an eligible class of actions (max R3) for one tool, a
destination pattern, a per-use cost ceiling, a number of uses and a validity window. It never
covers R4 or R5, never widens capabilities, and is consumed atomically by the broker.
"""

from __future__ import annotations

import fnmatch
import sqlite3
from dataclasses import dataclass

from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.money import Money
from storage import journal
from storage.db import require_transaction, transaction

RISK_ORDER = ["R0", "R1", "R2", "R3", "R4", "R5"]


@dataclass(frozen=True)
class Mandate:
    id: str
    tool_id: str
    destination_pattern: str
    max_risk: str
    max_cost: Money | None
    max_uses: int
    uses: int
    expires_at: str


class MandateStore:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def create(
        self,
        *,
        actor: Actor,
        employee_id: str,
        tool_id: str,
        destination_pattern: str,
        max_risk: str,
        max_uses: int,
        expires_at: str,
        max_cost: Money | None = None,
    ) -> str:
        if actor.kind != "owner" or actor.channel != "local_app" or not actor.strong_auth:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "mandates are granted by the owner in the local app")
        if max_risk not in ("R1", "R2", "R3"):
            raise AtlasError(ErrorCode.POLICY_DENIED, "mandates cover at most R3")
        if destination_pattern.strip() in ("*", "**", ""):
            raise AtlasError(ErrorCode.INVALID_INPUT, "a mandate needs a specific destination pattern")
        if parse_utc(expires_at) <= self.clock.now():
            raise AtlasError(ErrorCode.INVALID_INPUT, "mandate already expired")
        mid = new_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO mandates(id, owner_id, employee_id, tool_id, destination_pattern, max_risk,"
                " max_cost_minor, max_cost_currency, max_uses, uses, status, expires_at, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,0,'ACTIVE',?,?)",
                (
                    mid,
                    actor.id,
                    employee_id,
                    tool_id,
                    destination_pattern,
                    max_risk,
                    max_cost.amount_minor if max_cost else None,
                    max_cost.currency if max_cost else None,
                    max_uses,
                    expires_at,
                    to_utc_str(self.clock.now()),
                ),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=employee_id,
                type="mandate.granted",
                actor=actor,
                summary=f"mandate for {tool_id} to {destination_pattern}, max {max_risk}, {max_uses} use(s)",
            )
        return mid

    def find_applicable_in_txn(
        self, *, employee_id: str, tool_id: str, destination: str | None, cost: Money | None
    ) -> Mandate | None:
        require_transaction(self.conn)
        if destination is None:
            return None
        now = self.clock.now()
        for r in self.conn.execute(
            "SELECT * FROM mandates WHERE employee_id = ? AND tool_id = ? AND status = 'ACTIVE' ORDER BY created_at",
            (employee_id, tool_id),
        ):
            if parse_utc(r["expires_at"]) <= now:
                self.conn.execute("UPDATE mandates SET status = 'EXPIRED' WHERE id = ?", (r["id"],))
                continue
            if r["uses"] >= r["max_uses"]:
                continue
            if not fnmatch.fnmatchcase(destination, r["destination_pattern"]):
                continue
            ceiling = Money(r["max_cost_minor"], r["max_cost_currency"]) if r["max_cost_currency"] else None
            if cost is not None:
                if (
                    ceiling is None
                    or cost.currency != ceiling.currency
                    or cost.amount_minor > ceiling.amount_minor
                ):
                    continue
            return Mandate(
                r["id"],
                r["tool_id"],
                r["destination_pattern"],
                r["max_risk"],
                ceiling,
                r["max_uses"],
                r["uses"],
                r["expires_at"],
            )
        return None

    def consume_use_in_txn(self, mandate_id: str) -> None:
        require_transaction(self.conn)
        cur = self.conn.execute(
            "UPDATE mandates SET uses = uses + 1,"
            " status = CASE WHEN uses + 1 >= max_uses THEN 'EXHAUSTED' ELSE status END"
            " WHERE id = ? AND status = 'ACTIVE' AND uses < max_uses",
            (mandate_id,),
        )
        if cur.rowcount != 1:
            raise AtlasError(ErrorCode.APPROVAL_REQUIRED, "mandate no longer usable")

    def revoke(self, mandate_id: str, *, actor: Actor) -> None:
        if actor.kind != "owner":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner can revoke a mandate")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE mandates SET status = 'REVOKED', revoked_at = ? WHERE id = ? AND status = 'ACTIVE'",
                (to_utc_str(self.clock.now()), mandate_id),
            )
