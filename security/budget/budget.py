"""Budget reservations (spec 7.4, AT-012.1, GA-11).

Inference, paid tools and purchases are separate categories: authority to spend tokens is not
authority to buy anything. Before a billable call the broker reserves the maximum plausible cost
atomically; concurrent calls therefore respect the ceiling. ``null`` limits mean "pending owner
setup" and block paid calls. Periods are calendar months in UTC (documented simplification; the
owner's timezone can be adopted later without changing reservations already made).

Estimate, reported cost and reconciliation are kept separate: ``amount_minor`` is the reservation,
``settled_minor`` is what the provider reported.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.money import Money
from storage.db import require_transaction

CATEGORIES = ("inference", "paid_tool", "purchase")
_USAGE = (
    "SELECT COALESCE(SUM(CASE status WHEN 'RESERVED' THEN amount_minor"
    " WHEN 'SETTLED' THEN COALESCE(settled_minor, amount_minor) ELSE 0 END), 0) FROM budget_reservations"
)
_TASK_USAGE_SQL = _USAGE + " WHERE task_id = ? AND category IN ('inference','paid_tool')"
_PERIOD_USAGE_SQL = _USAGE + " WHERE period_key = ? AND category IN ('inference','paid_tool')"


class BudgetError(AtlasError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(
            ErrorCode.BUDGET_EXCEEDED,
            message,
            persisted="no reservation made; nothing dispatched",
            recommended_action="raise the limit or cancel; the task keeps its checkpoint",
        )
        self.reason = reason


@dataclass(frozen=True)
class BudgetLimits:
    currency: str
    monthly_limit_minor: int | None
    per_task_limit_minor: int | None
    warning_percentages: tuple[int, ...] = (70, 90)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> BudgetLimits:
        b = cfg["budget"]
        return cls(
            b["currency"],
            b["monthly_limit_minor"],
            b["per_task_limit_minor"],
            tuple(b["warning_percentages"]),
        )


@dataclass
class Reservation:
    id: str
    amount: Money
    warnings: list[str] = field(default_factory=list)


def period_key(clock: Clock) -> str:
    return clock.now().strftime("%Y-%m")


class BudgetManager:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, limits: BudgetLimits) -> None:
        self.conn = conn
        self.clock = clock
        self.limits = limits

    def _committed(self, scope: str, key: str) -> int:
        """Reserved + settled amount for a task or for a period (inference and paid tools only)."""
        sql = _TASK_USAGE_SQL if scope == "task" else _PERIOD_USAGE_SQL
        return int(self.conn.execute(sql, (key,)).fetchone()[0])

    def reserve_in_txn(
        self,
        *,
        task_id: str | None,
        category: str,
        amount: Money,
        purchase_ceiling: Money | None = None,
    ) -> Reservation:
        require_transaction(self.conn)
        if category not in CATEGORIES:
            raise BudgetError("UNKNOWN_CATEGORY", f"unknown budget category {category}")
        warnings: list[str] = []
        if category == "purchase":
            # Purchases never draw from the inference budget; they are bounded by the approved max cost.
            if purchase_ceiling is None:
                raise BudgetError("PURCHASE_WITHOUT_APPROVED_CEILING", "purchase needs an approved max cost")
            if (
                amount.currency != purchase_ceiling.currency
                or amount.amount_minor > purchase_ceiling.amount_minor
            ):
                raise BudgetError("PURCHASE_ABOVE_APPROVED_CEILING", "purchase exceeds the approved amount")
        else:
            lim = self.limits
            if lim.monthly_limit_minor is None or lim.per_task_limit_minor is None:
                raise BudgetError(
                    "NOT_CONFIGURED", "paid calls are blocked until the owner sets budget limits"
                )
            if amount.currency != lim.currency:
                raise BudgetError(
                    "CURRENCY_MISMATCH", f"budget is in {lim.currency}, cost in {amount.currency}"
                )
            task = self.conn.execute(
                "SELECT budget_amount_minor, budget_currency FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            task_limit = lim.per_task_limit_minor
            if task and task["budget_currency"] == lim.currency:
                task_limit = min(task_limit, task["budget_amount_minor"])
            task_used = self._committed("task", task_id) if task_id is not None else 0
            period = period_key(self.clock)
            period_used = self._committed("period", period)
            if task_used + amount.amount_minor > task_limit:
                raise BudgetError("TASK_LIMIT", "task budget would be exceeded")
            if period_used + amount.amount_minor > lim.monthly_limit_minor:
                raise BudgetError("PERIOD_LIMIT", "monthly budget would be exceeded")
            for pct in lim.warning_percentages:
                threshold = lim.monthly_limit_minor * pct // 100
                if period_used < threshold <= period_used + amount.amount_minor:
                    warnings.append(f"monthly budget crossed {pct}%")
        rid = new_id()
        self.conn.execute(
            "INSERT INTO budget_reservations(id, task_id, category, period_key, amount_minor, currency, status,"
            " created_at) VALUES (?,?,?,?,?,?,'RESERVED',?)",
            (
                rid,
                task_id,
                category,
                period_key(self.clock),
                amount.amount_minor,
                amount.currency,
                to_utc_str(self.clock.now()),
            ),
        )
        return Reservation(rid, amount, warnings)

    def settle_in_txn(self, reservation_id: str, reported: Money) -> None:
        require_transaction(self.conn)
        r = self.conn.execute("SELECT * FROM budget_reservations WHERE id = ?", (reservation_id,)).fetchone()
        if r is None or r["status"] != "RESERVED":
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "reservation not open")
        if reported.currency != r["currency"]:
            raise AtlasError(ErrorCode.INVALID_INPUT, "reported cost currency differs from reservation")
        self.conn.execute(
            "UPDATE budget_reservations SET status = 'SETTLED', settled_minor = ?, closed_at = ? WHERE id = ?",
            (reported.amount_minor, to_utc_str(self.clock.now()), reservation_id),
        )

    def release_in_txn(self, reservation_id: str) -> None:
        require_transaction(self.conn)
        self.conn.execute(
            "UPDATE budget_reservations SET status = 'RELEASED', closed_at = ? WHERE id = ? AND status = 'RESERVED'",
            (to_utc_str(self.clock.now()), reservation_id),
        )

    def period_usage(self) -> Money:
        used = self._committed("period", period_key(self.clock))
        return Money(used, self.limits.currency)
