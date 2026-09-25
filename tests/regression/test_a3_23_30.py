"""A3-23 (history reconciliation, core side) and A3-30 (controls derived from the state machine).

A3-23: every message carries a stable sequence; the app can fetch EVERYTHING after its last confirmed
sequence (no gap after 50+ messages) and see updates of messages it already has.
A3-30 / T30: the core returns available_actions per task; 'reevaluate' re-checks the blocking condition
and never turns an UNKNOWN external effect into a blind re-dispatch.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from shared.ids import new_id
from storage.db import transaction
from tests.conftest import World
from tests.helpers import insert_action, insert_task
from tests.integration.test_alpha2 import base_config, ok, save, send


def test_history_after_a_cursor_has_no_gaps(env: Any) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    first = send(c, env, conv, "mensagem 0")
    cursor = first["reply"]["sequence"]
    for i in range(1, 60):  # > 50 messages while the app was away
        send(c, env, conv, f"mensagem {i}")
    got: list[dict[str, Any]] = []
    after = cursor
    while True:
        page = ok(c.call("conversations.history", conversation_id=conv, after_sequence=after, limit=50))
        got += page["messages"]
        if not page["has_more"]:
            break
        after = page["messages"][-1]["sequence"]
    seqs = [m["sequence"] for m in got]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    assert len(got) == 59 * 2  # every owner message and reply after the cursor, none missing


def test_updated_message_is_visible_with_a_new_revision(env: Any, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(c, env, conv, "Faça um resumo do contrato")
    before = out["message"]
    delegated = send(c, env, conv, "delegar", intent="delegate", reply_to_message_id=before["message_id"])
    page = ok(c.call("conversations.history", conversation_id=conv))["messages"]
    now = next(m for m in page if m["message_id"] == before["message_id"])
    assert now["task_id"] == delegated["task_id"] and now["revision"] > before["revision"]
    changed = ok(
        c.call("conversations.history", conversation_id=conv, changed_since_revision=before["revision"])
    )
    assert before["message_id"] in [m["message_id"] for m in changed["messages"]]


def _task(world: World, state: str, blocked: str | None = None) -> str:
    with transaction(world.conn):
        tid = insert_task(world.conn, world.owner_id, world.employee.id, state="READY")
        if state != "READY":
            world.conn.execute(
                "UPDATE tasks SET state = ?, blocked_reason = ?, paused_from = ? WHERE id = ?",
                (state, blocked, "READY" if state == "PAUSED" else None, tid),
            )
    return tid


@pytest.mark.parametrize(
    ("state", "blocked", "expected"),
    [
        ("READY", None, {"pause", "cancel"}),
        ("WAITING_USER", None, {"pause", "cancel"}),
        ("WAITING_APPROVAL", None, {"pause", "cancel"}),
        ("PAUSED", None, {"resume", "cancel"}),
        ("BLOCKED", "BUDGET_EXCEEDED", {"reevaluate", "cancel"}),
        ("BLOCKED", "EXTERNAL_EFFECT_UNKNOWN", {"reconcile", "cancel"}),
        ("BLOCKED", "NO_PROGRESS", {"reevaluate", "cancel"}),
        ("COMPLETED", None, set()),
        ("CANCELLED", None, set()),
    ],
)
def test_available_actions_follow_the_state_machine(
    env: Any, world: World, state: str, blocked: str | None, expected: set[str]
) -> None:
    tid = _task(world, state, blocked)
    task = ok(env.connect().call("tasks.get", task_id=tid))["task"]
    assert set(task["available_actions"]) == expected  # before the fix: the app always offered all three
    assert (task["blocked_reason"] is None) == (state != "BLOCKED")


def test_reevaluate_after_budget_raise(env: Any, world: World) -> None:
    c = env.connect()
    ok(save(c, base_config(monthly_limit_minor=10, per_task_limit_minor=10)))
    tid = _task(world, "BLOCKED", "BUDGET_EXCEEDED")
    with transaction(world.conn):
        world.conn.execute(
            "INSERT INTO budget_reservations(id, task_id, category, period_key, amount_minor, currency, status,"
            " created_at) VALUES (?,?, 'inference', strftime('%Y-%m', 'now'), 10, 'USD', 'SETTLED', ?)",
            (new_id(), tid, "2026-01-01T00:00:00.000Z"),
        )
    ver = ok(c.call("tasks.get", task_id=tid))["task"]["version"]
    still = ok(c.call("tasks.reevaluate", task_id=tid, expected_version=ver))
    assert still["task"]["state"] == "BLOCKED" and "orçamento" in still["explanation"]
    ok(save(c, base_config(monthly_limit_minor=500, per_task_limit_minor=100)))
    ver = ok(c.call("tasks.get", task_id=tid))["task"]["version"]
    ready = ok(c.call("tasks.reevaluate", task_id=tid, expected_version=ver))
    assert ready["task"]["state"] == "READY"


def test_unknown_effect_is_never_redispatched_by_a_button(env: Any, world: World) -> None:
    c = env.connect()
    tid = _task(world, "BLOCKED", "EXTERNAL_EFFECT_UNKNOWN")
    with transaction(world.conn):
        insert_action(world.conn, tid, status="UNKNOWN")
    ver = ok(c.call("tasks.get", task_id=tid))["task"]["version"]
    out = ok(c.call("tasks.reevaluate", task_id=tid, expected_version=ver))
    assert out["task"]["state"] == "BLOCKED" and "conferir" in out["explanation"]
    resp = c.call("tasks.resume", task_id=tid, expected_version=ver)
    assert "error" in resp and json.dumps(resp).count("not paused") == 1
