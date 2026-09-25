"""A3-19 / T24: every reservation reads the budget revision in force, not a snapshot.

A client/broker built BEFORE the owner lowers the ceiling must respect the new ceiling on its very next
reservation. Consumption already recorded stays auditable. Controlled local model server; no cost.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.intelligence import IntelligenceSetup
from security.budget.budget import BudgetError, BudgetLimits, BudgetManager
from shared.money import Money
from storage.db import transaction
from storage.store import open_store
from tests.conftest import World
from tests.integration.test_alpha2 import base_config, configure_intelligence, ok, save
from tests.integration.test_openai_adapter import ok_body


def _save_settings(world: World, cfg: dict[str, Any]) -> None:
    """What another IPC connection does when the owner saves settings."""
    other = open_store(world.path, world.clock)
    with transaction(other):
        rev = other.execute("SELECT COALESCE(MAX(revision), 0) FROM settings").fetchone()[0]
        other.execute(
            "INSERT INTO settings(revision, config_json, updated_at, updated_by) VALUES (?,?,?,?)",
            (rev + 1, json.dumps(cfg), "2026-01-01T00:00:00.000Z", "owner:test"),
        )
    other.close()


def test_lowered_ceiling_applies_to_the_next_reservation(world: World) -> None:
    _save_settings(world, base_config(monthly_limit_minor=1_000, per_task_limit_minor=500))
    budget = BudgetManager.live(world.conn, world.clock)  # built before the change
    with transaction(world.conn):
        budget.reserve_in_txn(task_id=None, category="inference", amount=Money(300, "USD"))
    _save_settings(world, base_config(monthly_limit_minor=350, per_task_limit_minor=500))
    with pytest.raises(BudgetError) as exc, transaction(world.conn):
        budget.reserve_in_txn(task_id=None, category="inference", amount=Money(100, "USD"))
    assert exc.value.reason == "PERIOD_LIMIT"  # before the fix: allowed by the stale snapshot
    spent = world.conn.execute("SELECT SUM(amount_minor) FROM budget_reservations").fetchone()[0]
    assert spent == 300  # what was already reserved is not erased by the reduction
    _save_settings(world, base_config(monthly_limit_minor=2_000, per_task_limit_minor=500))
    with transaction(world.conn):  # raising it again allows new spending
        budget.reserve_in_txn(task_id=None, category="inference", amount=Money(100, "USD"))


def test_ceilings_removed_block_paid_calls(world: World) -> None:
    _save_settings(world, base_config())
    budget = BudgetManager.live(world.conn, world.clock)
    cfg = base_config()
    cfg["budget"]["monthly_limit_minor"] = None
    _save_settings(world, cfg)
    with pytest.raises(BudgetError) as exc, transaction(world.conn):
        budget.reserve_in_txn(task_id=None, category="inference", amount=Money(1, "USD"))
    assert exc.value.reason == "NOT_CONFIGURED"


def test_existing_model_client_obeys_the_new_ceiling(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)  # monthly 500, per task 40
    intel = IntelligenceSetup(world.conn, world.clock, env.make().intelligence.vault, base_url=env.base_url)
    client = intel.build_client()  # held by a worker across steps
    ok(save(c, base_config(accept_reference_prices=True, monthly_limit_minor=1, per_task_limit_minor=1)))
    api.queue.append((200, {}, ok_body(text='{"intent": "chat", "reply": "x", "objective": ""}')))
    from runtime.models.router import Requirements
    from runtime.models.types import Message, ModelRequest, Role

    with pytest.raises(BudgetError):
        client.call(
            task_id=None,
            employee_id=world.employee.id,
            purpose="conversation",
            req=Requirements(structured_output=True),
            request=ModelRequest("gpt-6-sol", (Message(Role.USER, "oi"),), max_output_tokens=64),
        )
    assert (
        api.requests[-1]["path"] != "/v1/responses"
        or len([r for r in api.requests if r["path"] == "/v1/responses"]) == 1
    )  # only the intelligence check itself reached the model; the blocked call was never sent


def test_snapshot_limits_still_work_for_isolated_components(world: World) -> None:
    b = BudgetManager(world.conn, world.clock, BudgetLimits("USD", 100, 100))
    with transaction(world.conn):
        b.reserve_in_txn(task_id=None, category="inference", amount=Money(50, "USD"))
