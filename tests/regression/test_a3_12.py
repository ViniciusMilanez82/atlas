"""A3-12 / T17: a task becomes visible to the worker only with its complete input package.

Two SQLite connections: the moment the task is first visible to another connection (the worker's), its
attachments, source message link, criteria and original instruction must already be committed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.artifacts.manager import ArtifactManager
from runtime.tasks.engine import TaskEngine
from storage.store import open_store
from tests.conftest import World
from tests.integration.test_alpha2 import ok, send

WORKER_VIEW = (
    "SELECT t.id, t.state,"
    " (SELECT COUNT(*) FROM artifact_links l WHERE l.task_id = t.id AND l.relation = 'input'),"
    " (SELECT COUNT(*) FROM messages m WHERE m.task_id = t.id),"
    " (SELECT COUNT(*) FROM task_criteria c WHERE c.task_id = t.id),"
    " (SELECT COUNT(*) FROM task_instruction_versions v WHERE v.task_id = t.id)"
    " FROM tasks t WHERE t.state IN ('CREATED','READY')"
)


def _attach(env: Any, world: World, tmp_path: Path, n: int) -> list[str]:
    am = ArtifactManager(world.conn, world.clock, env.store_root)
    ids = []
    for i in range(n):
        f = tmp_path / f"anexo{i}.txt"
        f.write_text(f"conteudo sintetico {i}", encoding="utf-8")
        ids.append(am.import_file(f, actor=world.owner, employee_id=world.employee.id).id)
    return ids


def test_worker_never_sees_a_task_without_its_attachments(
    env: Any, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the worker has its own connection (opened where it runs)
    seen: list[tuple[Any, ...]] = []
    original = TaskEngine.create

    def create_then_look(self: TaskEngine, *a: Any, **kw: Any) -> str:
        tid = original(self, *a, **kw)
        worker = open_store(world.path, world.clock)
        seen.extend(tuple(r) for r in worker.execute(WORKER_VIEW).fetchall())
        worker.close()  # right after the commit
        return tid

    monkeypatch.setattr(TaskEngine, "create", create_then_look)
    ids = _attach(env, world, tmp_path, 3)
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(c, env, conv, "Analise os tres anexos", intent="delegate", artifact_ids=ids)
    assert seen, "the worker should see the task once it is published"
    tid, state, inputs, msgs, criteria, versions = seen[0]
    assert tid == out["task_id"] and state == "CREATED"
    assert inputs == 3, "task was visible before its attachments were linked"
    assert msgs == 1 and criteria >= 1 and versions == 1


def test_tasks_create_links_attachments_in_the_same_commit(
    env: Any, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    seen: list[tuple[Any, ...]] = []
    original = TaskEngine.create

    def create_then_look(self: TaskEngine, *a: Any, **kw: Any) -> str:
        tid = original(self, *a, **kw)
        worker = open_store(world.path, world.clock)
        seen.extend(tuple(r) for r in worker.execute(WORKER_VIEW).fetchall())
        worker.close()
        return tid

    monkeypatch.setattr(TaskEngine, "create", create_then_look)
    ids = _attach(env, world, tmp_path, 2)
    c = env.connect()
    task = ok(
        c.call(
            "tasks.create",
            employee_id=world.employee.id,
            objective="Resumo dos anexos",
            artifact_ids=ids,
            constraints={"external_writes": False, "purchases": False},
        )
    )["task"]
    assert seen and seen[0][0] == task["task_id"] and seen[0][2] == 2


def test_invalid_attachment_publishes_nothing(env: Any, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    resp = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=conv,
        client_message_id="0f0f0f0f-0000-4000-8000-000000000001",
        text="Analise",
        intent="delegate",
        artifact_ids=["0f0f0f0f-0000-4000-8000-00000000ffff"],
    )
    assert resp["error"]["data"]["atlas_code"] == "INVALID_INPUT"
    assert world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0  # no orphan executable task
