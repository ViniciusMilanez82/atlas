"""A3-26 / T27: every exposed method relates session -> owner -> employee -> object.

Two synthetic identities (owner A/employee A, owner B/employee B) in the same database, over the real IPC
protocol. Every attempt to use an object of the other scope by ID must fail and reveal nothing of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.artifacts.manager import ArtifactManager
from runtime.memory.manager import MemoryManager
from shared.actors import Actor
from storage.repositories.identity import create_employee, create_owner
from tests.conftest import World
from tests.integration.test_alpha2 import ok

SECRET_TEXT = "conteudo-privado-de-B-4471"


@pytest.fixture
def two(env: Any, world: World, tmp_path: Path) -> dict[str, Any]:
    owner_b = create_owner(world.conn, world.clock, "Outro Proprietario")
    emp_b = create_employee(world.conn, world.clock, owner_id=owner_b, name="Atlas B")
    actor_b = Actor("owner", owner_b, "local_app", strong_auth=True)
    b = env.connect(actor=actor_b, employee_id=emp_b.id)
    conv_b = ok(b.call("conversations.current"))["conversation_id"]
    msg_b = ok(
        b.call(
            "conversations.send",
            employee_id=emp_b.id,
            conversation_id=conv_b,
            client_message_id="00000000-0000-4000-8000-00000000b001",
            text=SECRET_TEXT,
        )
    )["message_id"]
    task_b = ok(
        b.call(
            "tasks.create",
            employee_id=emp_b.id,
            objective=SECRET_TEXT,
            artifact_ids=[],
            constraints={"external_writes": False, "purchases": False},
            conversation_id=conv_b,
        )
    )["task"]
    mm = MemoryManager(world.conn, world.clock)
    src_b = mm.add_source(actor=actor_b, kind="owner_message", ref="b/1", employee_id=emp_b.id)
    mem_b = mm.propose(actor=actor_b, employee_id=emp_b.id, type="FACT", content=SECRET_TEXT, source_id=src_b)
    f = tmp_path / "b.txt"
    f.write_text(SECRET_TEXT, encoding="utf-8")
    art_b = ArtifactManager(world.conn, world.clock, env.store_root).import_file(
        f, actor=actor_b, employee_id=emp_b.id
    )
    a = env.connect()
    conv_a = ok(a.call("conversations.current"))["conversation_id"]
    return {
        "a": a,
        "conv_a": conv_a,
        "conv_b": conv_b,
        "msg_b": msg_b,
        "task_b": task_b,
        "mem_b": mem_b,
        "src_b": src_b,
        "art_b": art_b.id,
        "emp_b": emp_b.id,
    }


def _denied(resp: dict[str, Any]) -> None:
    assert "error" in resp, f"cross-scope call succeeded: {resp}"
    assert resp["error"]["data"]["atlas_code"] in ("UNAUTHORIZED", "INVALID_INPUT")
    assert SECRET_TEXT not in str(resp)  # nothing of the other scope is revealed


def test_cross_scope_matrix(two: dict[str, Any], world: World) -> None:
    a = two["a"]
    emp_a = world.employee.id
    calls = {
        "delegate B's message": (
            "conversations.send",
            {
                "employee_id": emp_a,
                "conversation_id": two["conv_a"],
                "client_message_id": "00000000-0000-4000-8000-00000000a001",
                "text": "delegar",
                "intent": "delegate",
                "reply_to_message_id": two["msg_b"],
            },
        ),
        "correct B's memory": (
            "memories.correct",
            {"memory_id": two["mem_b"], "expected_version": 1, "content": "novo", "source_id": two["src_b"]},
        ),
        "delete B's memory": ("memories.delete", {"memory_id": two["mem_b"]}),
        "confirm B's memory": ("memories.confirm", {"memory_id": two["mem_b"]}),
        "propose with B's source": (
            "memories.propose",
            {"memory_type": "FACT", "content": "x", "source_id": two["src_b"]},
        ),
        "read B's task": ("tasks.get", {"task_id": two["task_b"]["task_id"]}),
        "pause B's task": ("tasks.pause", {"task_id": two["task_b"]["task_id"], "expected_version": 1}),
        "correct B's task": (
            "tasks.update_instruction",
            {
                "task_id": two["task_b"]["task_id"],
                "text": "mude",
                "client_message_id": "00000000-0000-4000-8000-00000000a002",
            },
        ),
        "read B's artifact": ("artifacts.read", {"artifact_id": two["art_b"], "offset": 0, "length": 100}),
        "attach B's artifact": (
            "tasks.create",
            {
                "employee_id": emp_a,
                "objective": "usar anexo alheio",
                "artifact_ids": [two["art_b"]],
                "constraints": {"external_writes": False, "purchases": False},
            },
        ),
        "B's history": ("conversations.history", {"conversation_id": two["conv_b"]}),
        "send into B's conversation": (
            "conversations.send",
            {
                "employee_id": emp_a,
                "conversation_id": two["conv_b"],
                "client_message_id": "00000000-0000-4000-8000-00000000a003",
                "text": "oi",
            },
        ),
        "stop employee B": ("control.stop", {"employee_id": two["emp_b"]}),
        "task list of B": ("tasks.list", {"employee_id": two["emp_b"]}),
    }
    failures = []
    for label, (method, params) in calls.items():
        resp = a.call(method, **params)
        try:
            _denied(resp)
        except AssertionError as exc:
            failures.append(f"{label}: {exc}")
    assert not failures, "\n".join(failures)
    # and B's objects are untouched
    mem = world.conn.execute(
        "SELECT status, current_version FROM memories WHERE id = ?", (two["mem_b"],)
    ).fetchone()
    assert tuple(mem) == ("confirmed", 1)  # as B created it; A changed nothing
    assert (
        world.conn.execute("SELECT state FROM tasks WHERE id = ?", (two["task_b"]["task_id"],)).fetchone()[0]
        == "CREATED"
    )
