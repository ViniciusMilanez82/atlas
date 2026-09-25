"""R5-03 (P1; reopens A3-04): "pare tudo" also invalidates work still being interpreted. STOP is
interleaved at the four points of the review (receipt->inference, inference->publication,
publication->lease, lease->dispatch). The old request never starts a new effect after the stop is
applied; a genuinely new request, and an explicit resume, still work.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from runtime.tasks.state_machine import TaskState
from runtime.verification.verifier import DeliverableSpec
from shared.actors import Actor
from shared.errors import AtlasError
from shared.ids import new_id
from storage.db import transaction
from tests.regression.r5_harness import R5World, decision

DELEGATE = {"intent": "delegate", "reply": "", "objective": "Produza um relatório sobre fornecedores."}


def _cannot_run(r5: R5World, tid: str) -> None:
    calls = len(r5.provider.calls)
    with pytest.raises(AtlasError):
        r5.runner.run(tid, DeliverableSpec())
    assert r5.state(tid) == TaskState.PAUSED
    assert len(r5.provider.calls) == calls  # nothing was sent for the old request


def test_stop_during_interpretation_publishes_paused(r5: R5World) -> None:
    """The reviewer's case: STOP lands while the model interprets the message (inference->publication)."""
    r5.provider.reply = DELEGATE

    def stop(_: Any) -> None:
        r5.provider.hook = None
        r5.tasks.stop_all(actor=r5.owner, employee_id=r5.emp.id)

    r5.provider.hook = stop
    out = r5.send("Produza um relatório sobre fornecedores.")
    tid = out["task_id"]
    assert out["intent"] == "delegate_paused"
    assert r5.state(tid) == TaskState.PAUSED  # persisted (nothing lost), not executable
    assert "PAUSADA" in out["reply"]["content"]
    _cannot_run(r5, tid)


def test_stop_between_receipt_and_inference(r5: R5World) -> None:
    r5.provider.reply = DELEGATE
    p = {"conversation_id": r5.cid, "client_message_id": new_id(), "text": "Produza um relatório sobre fornecedores."}
    r5.conv.receive(r5.owner, r5.emp.id, p, claim=False)  # durably received, not processed yet
    r5.tasks.stop_all(actor=r5.owner, employee_id=r5.emp.id)
    out = r5.conv.handle(r5.owner, r5.emp.id, dict(p))  # processed (resumed) after the stop
    assert r5.state(out["task_id"]) == TaskState.PAUSED
    _cannot_run(r5, out["task_id"])


def test_stop_between_publication_and_lease(r5: R5World) -> None:
    out = r5.send("Produza um relatório sobre fornecedores.", intent="delegate")
    tid = out["task_id"]
    r5.runner._prepare(tid)
    assert r5.state(tid) == TaskState.READY
    r5.tasks.stop_all(actor=r5.owner, employee_id=r5.emp.id)
    _cannot_run(r5, tid)
    # Defense in depth: even a READY row authorized under an older epoch is never leased.
    with transaction(r5.conn):
        r5.conn.execute("UPDATE tasks SET state = 'READY', paused_from = NULL WHERE id = ?", (tid,))
    with pytest.raises(AtlasError):
        r5.tasks.acquire_lease(tid, "late-worker")
    assert r5.state(tid) == TaskState.PAUSED


def test_stop_between_lease_and_dispatch(r5: R5World) -> None:
    tid = r5.send("Produza um relatório sobre fornecedores.", intent="delegate")["task_id"]
    r5.runner._prepare(tid)
    lease = r5.tasks.acquire_lease(tid, "w")
    r5.tasks.stop_all(actor=r5.owner, employee_id=r5.emp.id)
    proposal = {
        "schema_version": "1.0", "task_id": tid, "step_id": new_id(), "tool_id": "calc.evaluate",
        "tool_version": "1.0.0", "input": {"expression": "1+1"}, "expected_outcome": "x",
        "verification": {"kind": "deterministic_check", "required": True}, "instruction_revision": 1,
    }
    with pytest.raises(AtlasError):
        r5.broker.submit(proposal, lease)
    assert r5.conn.execute("SELECT COUNT(*) FROM actions WHERE task_id = ? AND status = 'CONFIRMED'", (tid,)).fetchone()[0] == 0


def test_new_request_and_explicit_resume_still_work(r5: R5World) -> None:
    r5.provider.reply = DELEGATE

    def stop(_: Any) -> None:
        r5.provider.hook = None
        r5.tasks.stop_all(actor=r5.owner, employee_id=r5.emp.id)

    r5.provider.hook = stop
    old = r5.send("Produza um relatório sobre fornecedores.")["task_id"]
    # A greeting does not release the paused work.
    r5.provider.reply = {"intent": "chat", "reply": "Olá!", "objective": ""}
    r5.send("Bom dia, tudo certo por aí?")
    assert r5.state(old) == TaskState.PAUSED
    # A request made AFTER the stop is new, authorized work.
    new = r5.send("Escreva um resumo sobre maçãs.", intent="delegate")
    assert new["intent"] == "delegate" and r5.state(new["task_id"]) == TaskState.CREATED
    r5.provider.reply = decision("ask_owner", question="Quantas páginas?")
    assert r5.runner.run(new["task_id"], DeliverableSpec()).state == TaskState.WAITING_USER
    # The owner's explicit resume authorizes the old task under the current epoch.
    r5.tasks.resume(old, actor=r5.owner, expected_version=r5.tasks.get(old)["version"])
    assert r5.runner.run(old, DeliverableSpec()).state == TaskState.WAITING_USER


def test_subtask_of_a_stopped_parent_and_restart(r5: R5World) -> None:
    parent = r5.send("Produza um relatório sobre fornecedores.", intent="delegate")["task_id"]
    r5.tasks.stop_all(actor=r5.owner, employee_id=r5.emp.id)
    child = r5.tasks.create(
        Actor("runtime", "agent", "internal"), employee_id=r5.emp.id, objective="subtarefa", parent_task_id=parent
    )
    assert r5.state(child) == TaskState.PAUSED
    r5.tasks.recover_after_restart()  # a restart does not make old work executable
    r5.conv.recover_receipts()
    assert r5.state(child) == TaskState.PAUSED and r5.state(parent) == TaskState.PAUSED


def test_stop_on_a_second_connection_while_interpretation_hangs(env: Any, api: Any) -> None:
    """Two real IPC connections: the chat request is inside the model call when control.stop arrives
    on the control lane; the late 'delegate' answer publishes a PAUSED task."""
    from tests.integration.test_alpha2 import configure_intelligence, ok, send
    from tests.integration.test_openai_adapter import ok_body

    chat, control = env.connect(), env.connect()
    configure_intelligence(chat, api)
    conv = ok(chat.call("conversations.current"))["conversation_id"]
    gate = threading.Event()
    api.queue.append((200, {}, ("gate", gate, ok_body(text=json.dumps(DELEGATE)))))
    box: dict[str, Any] = {}
    before = len(api.requests)  # the key validation already called /responses
    t = threading.Thread(target=lambda: box.update(out=send(chat, env, conv, "Produza um relatório.")), daemon=True)
    t.start()
    deadline = time.monotonic() + 5
    while not any(r["path"].endswith("/responses") for r in api.requests[before:]) and time.monotonic() < deadline:
        time.sleep(0.02)
    rep = ok(control.call("control.stop", employee_id=env.world.employee.id))
    assert rep["control_epoch"] >= 1
    gate.set()
    t.join(10)
    out = box["out"]
    assert out["intent"] == "delegate_paused"
    task = ok(control.call("tasks.get", task_id=out["task_id"]))["task"]
    assert task["state"] == "PAUSED"
