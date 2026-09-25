"""A3-11 / T16: a resend with the same client_message_id recovers an interrupted request.

Fault injection in the real ConversationService (crash = an exception that aborts the handler, like
a process dying): after the message is received, after the model decided, after the task was created
and before the reply. The resend must finish the SAME request exactly once; a different payload with
the same id is a conflict. Controlled local model server (no network).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.conversation import ConversationService
from shared.ids import new_id
from tests.conftest import World
from tests.integration.test_alpha2 import configure_intelligence, ok, send
from tests.integration.test_openai_adapter import ok_body


class Crash(Exception):
    """Stands in for the process dying at this point."""


def _once(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    original = getattr(ConversationService, name)
    state = {"armed": True}

    def wrapper(self: ConversationService, *a: Any, **kw: Any) -> Any:
        if state["armed"]:
            state["armed"] = False
            raise Crash(name)
        return original(self, *a, **kw)

    monkeypatch.setattr(ConversationService, name, wrapper)


def _counts(world: World) -> tuple[int, int, int]:
    q = world.conn.execute
    return (
        q("SELECT COUNT(*) FROM messages WHERE role = 'owner'").fetchone()[0],
        q("SELECT COUNT(*) FROM messages WHERE role = 'employee'").fetchone()[0],
        q("SELECT COUNT(*) FROM tasks").fetchone()[0],
    )


@pytest.mark.parametrize("point", ["_route", "say"])
def test_delegation_resumes_after_a_crash(
    env: Any, world: World, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    mid = new_id()
    _once(monkeypatch, point)
    first = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=conv,
        client_message_id=mid,
        text="Compare as propostas",
        intent="delegate",
    )
    assert "error" in first  # the handler died mid-way
    again = send(c, env, conv, "Compare as propostas", intent="delegate", client_message_id=mid)
    # before the fix: intent 'duplicate' with reply None forever
    assert again["reply"] is not None and again["reply"]["kind"] == "ack"
    assert again["task_id"] is not None
    third = send(c, env, conv, "Compare as propostas", intent="delegate", client_message_id=mid)
    assert third["duplicate"] is True and third["reply"]["message_id"] == again["reply"]["message_id"]
    assert _counts(world) == (1, 1, 1)  # one owner message, one reply, one task
    row = world.conn.execute("SELECT state FROM request_receipts WHERE request_key = ?", (mid,)).fetchone()
    assert row[0] == "COMPLETED"


def test_chat_after_inference_does_not_call_the_model_again(
    env: Any, api: Any, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    api.queue.append(
        (200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "Bom dia!", "objective": ""})))
    )
    calls_before = len(api.requests)
    _once(monkeypatch, "say")  # dies after the (billed) model decision, before the reply exists
    mid = new_id()
    first = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=conv,
        client_message_id=mid,
        text="Bom dia",
    )
    assert "error" in first
    again = send(c, env, conv, "Bom dia", client_message_id=mid)
    assert again["reply"]["content"] == "Bom dia!"
    assert len(api.requests) - calls_before == 1  # the recorded decision was reused, not re-billed


def test_same_id_with_different_payload_is_a_conflict(env: Any, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    mid = new_id()
    send(c, env, conv, "Compare as propostas", intent="delegate", client_message_id=mid)
    resp = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=conv,
        client_message_id=mid,
        text="Outro texto",
        intent="delegate",
    )
    assert resp["error"]["data"]["atlas_code"] == "VERSION_CONFLICT"
    assert _counts(world) == (1, 1, 1)


def test_request_in_progress_is_reported_as_processing(env: Any, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    mid = new_id()
    svc = env.make().conversation
    svc.receive(
        world.owner,
        world.employee.id,
        {"conversation_id": conv, "client_message_id": mid, "text": "Oi"},
        claim=True,
    )  # another worker holds the processing lease
    out = send(c, env, conv, "Oi", client_message_id=mid)
    assert out["intent"] == "processing" and out["reply"] is None and out["receipt_state"] == "PROCESSING"
