"""A3-18 / T09: the current message and active instructions are in every inference (or the call is
refused with a reason); an earlier model reply is never presented as a verified fact.

Assertions are on the payload that actually reached the (controlled, local) model server.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.models.context import Authority, ContextBuilder, ContextItem, ContextOverflow
from shared.ids import new_id
from storage.db import transaction
from tests.conftest import World
from tests.integration.test_alpha2 import configure_intelligence, ok, send
from tests.integration.test_openai_adapter import ok_body

UNVERIFIED_CLAIM = "SENTINELA-NAO-VERIFICADA: o contrato vence em 2020"


def _flood(world: World, conv: str, n: int, size: int) -> None:
    with transaction(world.conn):
        for i in range(n):
            role = "owner" if i % 2 == 0 else "employee"
            text = (UNVERIFIED_CLAIM + " ") if (role == "employee" and i == 1) else ""
            world.conn.execute(
                "INSERT INTO messages(id, conversation_id, role, origin, client_message_id, content, kind, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    conv,
                    role,
                    "local_app" if role == "owner" else "system",
                    None,
                    text + f"mensagem antiga {i} " + "x" * size,
                    "chat",
                    f"2026-01-01T00:00:{i % 60:02d}.000Z",
                ),
            )


def test_current_message_survives_a_saturated_history(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    _flood(world, conv, n=20, size=6_000)  # far above the context budget
    api.queue.append((200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "ok", "objective": ""}))))
    current = "Correcao: use prazo, nao preco. Detalhes: " + "d" * 4_000 + " FIM-DA-CORRECAO"
    send(c, env, conv, current)
    body = api.requests[-1]["body"]
    payload = body["instructions"] + "\n".join(m["content"] for m in body["input"])
    assert "FIM-DA-CORRECAO" in payload  # before the fix: older messages filled the budget first


def test_an_earlier_model_reply_is_not_a_verified_fact(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    _flood(world, conv, n=2, size=10)
    api.queue.append((200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "ok", "objective": ""}))))
    send(c, env, conv, "E quando vence o contrato?")
    body = api.requests[-1]["body"]
    payload = body["instructions"] + "\n".join(m["content"] for m in body["input"])
    assert UNVERIFIED_CLAIM in payload
    idx = payload.index(UNVERIFIED_CLAIM)
    before = payload[max(0, idx - 200) : idx]
    assert "VERIFIED FACT" not in before and "unverified" in before.lower()  # before the fix: VERIFIED FACT


def test_required_items_are_reserved_before_history() -> None:
    items = [ContextItem(Authority.POLICY, "regras", "policy", required=True)]
    items += [ContextItem(Authority.CONVERSATION, "h" * 3_000, f"message:{i}") for i in range(30)]
    items.append(ContextItem(Authority.OWNER_INSTRUCTION, "pedido atual", "message:now", required=True))
    built = ContextBuilder(max_chars=12_000).build(items)
    assert "message:now" in built.included and "policy" in built.included
    assert built.dropped and all(ref.startswith("message:") and ref != "message:now" for ref in built.dropped)
    kept = [ref for ref in built.included if ref.startswith("message:") and ref != "message:now"]
    assert kept == sorted(kept, key=lambda r: int(r.split(":")[1]))  # chronological order kept
    assert "message:29" in kept  # recency wins within the same authority


def test_required_context_that_does_not_fit_blocks_the_call() -> None:
    items = [ContextItem(Authority.OWNER_INSTRUCTION, "y" * 20_000, "message:now", required=True)]
    with pytest.raises(ContextOverflow):
        ContextBuilder(max_chars=4_000).build(items)
