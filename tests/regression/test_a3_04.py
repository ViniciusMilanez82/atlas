"""A3-04 / T20 (core side): "stop" has its own lane, independent of a slow conversation/model call.

Real IPC protocol over socket pairs and a CONTROLLED LOCAL model server that hangs (no network). The
app side (button/shortcut on a separate connection, not blocked by isSending) is covered by
platform/macos/AtlasKit/Tests/AtlasKitTests/A304RegressionTests.swift on the macOS runner.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from storage.db import transaction
from tests.conftest import World
from tests.helpers import insert_action, insert_task
from tests.integration.test_alpha2 import configure_intelligence, ok, send


def test_stop_is_applied_while_a_chat_call_hangs(env: Any, api: Any, world: World) -> None:
    chat, control = env.connect(), env.connect()
    configure_intelligence(chat, api)
    conv = ok(chat.call("conversations.current"))["conversation_id"]
    with transaction(world.conn):
        running = insert_task(world.conn, world.owner_id, world.employee.id, state="READY")
        queued = insert_task(world.conn, world.owner_id, world.employee.id, state="READY")
        insert_action(world.conn, running, status="DISPATCHING")
    api.queue.append((200, {}, "hang"))  # the model never answers in time
    pending = threading.Thread(target=lambda: send(chat, env, conv, "Me explique o contrato"), daemon=True)
    pending.start()
    time.sleep(0.2)  # the chat request is now blocked inside the model call

    t0 = time.monotonic()
    rep = ok(control.call("control.stop", employee_id=world.employee.id))
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"stop waited behind the conversation ({elapsed:.2f}s)"
    assert pending.is_alive()  # proof the conversation lane was still blocked
    assert set(rep["paused_tasks"]) == {running, queued}
    assert len(rep["in_flight_actions"]) == 1  # reported as already sent, not as undone
    assert rep["control_epoch"] == 1
    for tid in (running, queued):
        assert world.conn.execute("SELECT state FROM tasks WHERE id = ?", (tid,)).fetchone()[0] == "PAUSED"
    order = world.conn.execute("SELECT kind, control_epoch, applied_at FROM control_orders").fetchone()
    assert order[0] == "STOP_ALL" and order[1] == 1 and order[2]
    pending.join(10)


def test_stop_needs_the_owner_or_a_paired_device(env: Any, world: World) -> None:
    from shared.actors import Actor

    runtime = env.connect(actor=Actor("runtime", "rt", "internal"))
    resp = runtime.call("control.stop", employee_id=world.employee.id)
    assert resp["error"]["data"]["atlas_code"] == "UNAUTHORIZED"
