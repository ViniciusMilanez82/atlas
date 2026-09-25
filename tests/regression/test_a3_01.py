"""A3-01 / T04: free conversation recovers durable memory outside the recent window, after a restart,
asked with different words; unconfirmed proposals never become authority.

The CONTEXT sent to the (controlled, local) model is inspected - not a lucky reply.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.memory.manager import MemoryManager
from shared.ids import new_id
from storage.db import transaction
from tests.conftest import World
from tests.integration.test_alpha2 import configure_intelligence, ok, send
from tests.integration.test_openai_adapter import ok_body

CHAT_OK = json.dumps({"intent": "chat", "reply": "ok", "objective": ""})


def _filler(world: World, conv: str, n: int) -> None:
    with transaction(world.conn):
        for i in range(n):
            world.conn.execute(
                "INSERT INTO messages(id, conversation_id, role, origin, content, kind, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    new_id(),
                    conv,
                    "owner" if i % 2 == 0 else "employee",
                    "local_app" if i % 2 == 0 else "system",
                    f"assunto aleatorio numero {i} sobre futebol, receitas e viagens",
                    "chat",
                    "2026-01-01T00:00:00.000Z",
                ),
            )


def _last_payload(api: Any) -> str:
    body = [r for r in api.requests if r["path"].endswith("/responses")][-1]["body"]
    return str(body["instructions"]) + "\n" + "\n".join(m["content"] for m in body["input"])


def test_confirmed_fact_is_recovered_after_many_messages_and_restart(
    env: Any, api: Any, world: World
) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    fact = send(c, env, conv, "Guarde que o nome do meu cachorro é Thor")
    ok(c.call("memories.confirm", memory_id=fact["memory_id"]))
    unconfirmed = send(c, env, conv, "Guarde que meu time do coração é o Náutico")  # never confirmed
    _filler(world, conv, 120)  # far outside the 20-message window
    c2 = env.connect()  # restart: a new session and service
    api.queue.append((200, {}, ok_body(text=CHAT_OK)))
    send(c2, env, conv, "Como se chama o meu cão?")
    payload = _last_payload(api)
    assert f"OWNER-CONFIRMED MEMORY [memory:{fact['memory_id']}" in payload  # before the fix: absent
    assert "Thor" in payload
    assert f"memory:{unconfirmed['memory_id']}" not in payload  # a proposal is not authority


def test_paraphrase_finds_the_right_memory_among_many(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    mm = MemoryManager(world.conn, world.clock)
    src = mm.add_source(actor=world.owner, kind="owner_message", ref="t", employee_id=world.employee.id)
    for i in range(30):
        mm.propose(
            actor=world.owner,
            employee_id=world.employee.id,
            type="FACT",
            content=f"Fornecedor numero {i} entrega parafusos na zona {i}",
            source_id=src,
        )
    target = mm.propose(
        actor=world.owner,
        employee_id=world.employee.id,
        type="FACT",
        content="Minha cor preferida é verde-musgo",
        source_id=src,
    )
    api.queue.append((200, {}, ok_body(text=CHAT_OK)))
    send(c, env, conv, "Qual é a minha cor favorita?")
    payload = _last_payload(api)
    assert f"memory:{target}" in payload and "verde-musgo" in payload
    assert payload.count("OWNER-CONFIRMED MEMORY") <= 10  # the database is not dumped into the context


def test_preferences_apply_without_matching_words(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    mm = MemoryManager(world.conn, world.clock)
    src = mm.add_source(actor=world.owner, kind="owner_message", ref="t", employee_id=world.employee.id)
    pref = mm.propose(
        actor=world.owner,
        employee_id=world.employee.id,
        type="PREFERENCE",
        content="Responda sempre de forma curta e direta",
        source_id=src,
    )
    api.queue.append((200, {}, ok_body(text=CHAT_OK)))
    send(c, env, conv, "Bom dia! O que acha do plano de marketing?")
    assert f"memory:{pref}" in _last_payload(api)


def test_no_memory_is_invented_when_nothing_matches(env: Any, api: Any) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    api.queue.append((200, {}, ok_body(text=CHAT_OK)))
    send(c, env, conv, "Qual é o meu signo?")
    assert "OWNER-CONFIRMED MEMORY" not in _last_payload(api)
