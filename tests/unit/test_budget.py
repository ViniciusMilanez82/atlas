"""AT-012.1 / GA-11 / T-09: budget ceilings with concurrent reservations."""

from __future__ import annotations

import threading

import pytest

from security.budget.budget import BudgetError, BudgetLimits, BudgetManager
from shared.money import Money
from storage.db import transaction
from storage.store import open_store
from tests.conftest import World
from tests.helpers import insert_task

LIMITS = BudgetLimits("USD", monthly_limit_minor=1000, per_task_limit_minor=600)


def task(world: World) -> str:
    with transaction(world.conn):
        return insert_task(world.conn, world.owner_id, world.employee.id)


def reserve(world: World, bm: BudgetManager, tid: str, amount: int, cat: str = "inference") -> str:
    with transaction(world.conn):
        return bm.reserve_in_txn(task_id=tid, category=cat, amount=Money(amount, "USD")).id


def test_not_configured_blocks_paid_calls(world: World) -> None:
    bm = BudgetManager(world.conn, world.clock, BudgetLimits("USD", None, None))
    with pytest.raises(BudgetError) as e:
        reserve(world, bm, task(world), 1)
    assert e.value.reason == "NOT_CONFIGURED"


def test_task_and_period_limits(world: World) -> None:
    bm = BudgetManager(world.conn, world.clock, LIMITS)
    t1, t2 = task(world), task(world)
    reserve(world, bm, t1, 600)
    with pytest.raises(BudgetError) as e:
        reserve(world, bm, t1, 1)
    assert e.value.reason == "TASK_LIMIT"
    reserve(world, bm, t2, 400)
    with pytest.raises(BudgetError) as e:
        reserve(world, bm, task(world), 1)
    assert e.value.reason == "PERIOD_LIMIT"


def test_warnings_at_70_and_90(world: World) -> None:
    bm = BudgetManager(world.conn, world.clock, BudgetLimits("USD", 1000, 1000))
    tid = task(world)
    with transaction(world.conn):
        r1 = bm.reserve_in_txn(task_id=tid, category="inference", amount=Money(650, "USD"))
        r2 = bm.reserve_in_txn(task_id=tid, category="inference", amount=Money(100, "USD"))
        r3 = bm.reserve_in_txn(task_id=tid, category="inference", amount=Money(200, "USD"))
    assert r1.warnings == []
    assert r2.warnings == ["monthly budget crossed 70%"]
    assert r3.warnings == ["monthly budget crossed 90%"]


def test_release_and_settle(world: World) -> None:
    bm = BudgetManager(world.conn, world.clock, LIMITS)
    tid = task(world)
    rid = reserve(world, bm, tid, 500)
    with transaction(world.conn):
        bm.release_in_txn(rid)
    rid2 = reserve(world, bm, tid, 500)
    with transaction(world.conn):
        bm.settle_in_txn(rid2, Money(120, "USD"))  # provider reported less than reserved
    assert bm.period_usage() == Money(120, "USD")


def test_currency_mismatch(world: World) -> None:
    bm = BudgetManager(world.conn, world.clock, LIMITS)
    tid = task(world)
    with pytest.raises(BudgetError) as e, transaction(world.conn):
        bm.reserve_in_txn(task_id=tid, category="inference", amount=Money(1, "BRL"))
    assert e.value.reason == "CURRENCY_MISMATCH"


def test_purchase_does_not_use_inference_budget_and_needs_ceiling(world: World) -> None:
    bm = BudgetManager(world.conn, world.clock, BudgetLimits("USD", None, None))
    tid = task(world)
    with pytest.raises(BudgetError) as e, transaction(world.conn):
        bm.reserve_in_txn(task_id=tid, category="purchase", amount=Money(100, "BRL"))
    assert e.value.reason == "PURCHASE_WITHOUT_APPROVED_CEILING"
    with pytest.raises(BudgetError) as e, transaction(world.conn):
        bm.reserve_in_txn(
            task_id=tid, category="purchase", amount=Money(101, "BRL"), purchase_ceiling=Money(100, "BRL")
        )
    assert e.value.reason == "PURCHASE_ABOVE_APPROVED_CEILING"


def test_concurrent_reservations_respect_ceiling(world: World) -> None:
    """Twenty workers race for 100 each against a 1000 ceiling: exactly 10 win."""
    limits = BudgetLimits("USD", 1000, 1000)
    tid = task(world)
    wins: list[str] = []
    losses: list[str] = []

    def worker() -> None:
        conn = open_store(world.path, world.clock)
        bm = BudgetManager(conn, world.clock, limits)
        try:
            with transaction(conn):
                bm.reserve_in_txn(task_id=tid, category="inference", amount=Money(100, "USD"))
            wins.append("ok")
        except BudgetError:
            losses.append("limit")
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 10
    assert len(losses) == 10
    total = world.conn.execute("SELECT SUM(amount_minor) FROM budget_reservations").fetchone()[0]
    assert total == 1000
