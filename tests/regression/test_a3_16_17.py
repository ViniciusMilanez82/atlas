"""A3-16 (correction keeps the validity window) and A3-17 (forgetting reaches every copy under Atlas
control, survives restart and backup restore) - scenarios T06, T07.

Synthetic sentinel; the model payload is inspected at the controlled local server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.memory.manager import MemoryManager
from shared.errors import AtlasError
from storage.backup.backup import create_backup, restore_backup
from storage.store import open_store
from tests.conftest import World
from tests.integration.test_alpha2 import configure_intelligence, ok, send
from tests.integration.test_openai_adapter import ok_body

SENTINEL = "CODIGO-INTERNO-5591"


def _mm(world: World) -> tuple[MemoryManager, str]:
    mm = MemoryManager(world.conn, world.clock)
    return mm, mm.add_source(actor=world.owner, kind="owner_message", ref="t", employee_id=world.employee.id)


def test_text_correction_keeps_an_expired_window(world: World) -> None:
    mm, src = _mm(world)
    mid = mm.propose(
        actor=world.owner,
        employee_id=world.employee.id,
        type="FACT",
        content="Endereco provisorio da obra: Rua A",
        source_id=src,
        valid_from="2025-01-01T00:00:00.000Z",
        valid_until="2025-06-01T00:00:00.000Z",
    )
    assert mm.search(employee_id=world.employee.id, query="provisorio") == []  # expired (clock = 2026)
    mm.correct(
        mid,
        actor=world.owner,
        expected_version=1,
        content="Endereco provisorio da obra: Rua B",
        source_id=src,
    )
    assert mm.search(employee_id=world.employee.id, query="provisorio") == []  # before the fix: came back
    v = world.conn.execute(
        "SELECT valid_from, valid_until FROM memory_versions WHERE memory_id = ? AND version = 2", (mid,)
    ).fetchone()
    assert tuple(v) == ("2025-01-01T00:00:00.000Z", "2025-06-01T00:00:00.000Z")


def test_text_correction_keeps_a_future_window_and_explicit_change_is_allowed(world: World) -> None:
    mm, src = _mm(world)
    mid = mm.propose(
        actor=world.owner,
        employee_id=world.employee.id,
        type="FACT",
        content="Ferias coletivas em julho",
        source_id=src,
        valid_from="2026-07-01T00:00:00.000Z",
    )
    mm.correct(
        mid, actor=world.owner, expected_version=1, content="Ferias coletivas em agosto", source_id=src
    )
    assert mm.search(employee_id=world.employee.id, query="ferias") == []  # still in the future
    mm.correct(
        mid,
        actor=world.owner,
        expected_version=2,
        content="Ferias coletivas em agosto",
        source_id=src,
        valid_from=None,
        change_validity=True,
    )  # the owner explicitly removes the start date
    assert [h.content for h in mm.search(employee_id=world.employee.id, query="ferias")] == [
        "Ferias coletivas em agosto"
    ]
    with pytest.raises(AtlasError):
        mm.correct(
            mid,
            actor=world.owner,
            expected_version=3,
            content="x",
            source_id=src,
            valid_from="2026-09-01T00:00:00.000Z",
            valid_until="2026-08-01T00:00:00.000Z",
            change_validity=True,
        )


def _payloads(api: Any) -> str:
    return json.dumps([r["body"] for r in api.requests if r["path"].endswith("/responses")])


def test_erase_reaches_history_context_restart_and_restore(
    env: Any, api: Any, world: World, tmp_path: Path
) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(c, env, conv, f"Guarde que o codigo interno do projeto e {SENTINEL}")
    ok(c.call("memories.confirm", memory_id=out["memory_id"]))
    backup = tmp_path / "bk"
    create_backup(world.conn, backup, world.clock)  # taken BEFORE the owner forgets it

    preview = ok(c.call("memories.forget_preview", memory_id=out["memory_id"]))
    assert preview["messages"] >= 2 and preview["memory_versions"] >= 1  # request + confirmation echo
    ok(c.call("memories.delete", memory_id=out["memory_id"], scope="erase"))

    api.queue.append((200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "ok", "objective": ""}))))
    send(c, env, conv, "Qual e o codigo do projeto?")
    assert SENTINEL not in _payloads(api)  # before the fix: the request/echo messages carried it
    hist = json.dumps(ok(c.call("conversations.history", conversation_id=conv)))
    assert SENTINEL not in hist
    c2 = env.connect()  # restart
    assert SENTINEL not in json.dumps(ok(c2.call("conversations.history", conversation_id=conv)))

    # The live database stays open by the IPC threads on this host, so the restore targets a consistent
    # copy of the CURRENT state (with its tombstones), exactly what restore_backup reads before swapping.
    import sqlite3

    current = tmp_path / "current.sqlite"
    dst = sqlite3.connect(str(current))
    world.conn.backup(dst)
    dst.close()
    restore_backup(backup, current, world.clock)  # tombstones are carried and re-applied
    restored = open_store(current, world.clock)
    rows = restored.execute("SELECT content FROM messages").fetchall()
    assert all(SENTINEL not in r[0] for r in rows)  # the backup had it; the restore removed it again
    mem = restored.execute("SELECT content FROM memory_versions").fetchall()
    assert all(SENTINEL not in r[0] for r in mem)
    assert restored.execute("SELECT COUNT(*) FROM forget_tombstones").fetchone()[0] == 1
    restored.close()


def test_forgotten_content_is_not_reintroduced_by_a_derived_source(world: World) -> None:
    mm, src = _mm(world)
    mid = mm.propose(
        actor=world.owner, employee_id=world.employee.id, type="FACT", content=SENTINEL, source_id=src
    )
    mm.delete(mid, actor=world.owner, scope="erase")
    doc = mm.add_source(actor=world.owner, kind="document", ref="resumo", employee_id=world.employee.id)
    with pytest.raises(AtlasError) as exc:
        mm.propose(
            actor=world.owner, employee_id=world.employee.id, type="FACT", content=SENTINEL, source_id=doc
        )
    assert "forgotten" in exc.value.message


def test_stop_using_blocks_retrieval_and_context_but_keeps_the_history_visible(
    env: Any, api: Any, world: World
) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(c, env, conv, f"Guarde que o codigo interno do projeto e {SENTINEL}")
    ok(c.call("memories.confirm", memory_id=out["memory_id"]))
    ok(c.call("memories.delete", memory_id=out["memory_id"], scope="stop_using"))
    assert ok(c.call("memories.search", employee_id=world.employee.id, query="codigo interno"))["hits"] == []
    api.queue.append((200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "ok", "objective": ""}))))
    send(c, env, conv, "Bom dia")
    assert SENTINEL not in _payloads(api)
    assert SENTINEL in json.dumps(ok(c.call("conversations.history", conversation_id=conv)))
