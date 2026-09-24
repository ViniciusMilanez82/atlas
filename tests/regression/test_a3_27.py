"""A3-27 / T18: a question or result for the owner is never lost after the task changed state.

The notification is written in the SAME transaction as the state change; delivery into the conversation
is a separate, repeatable step that records exactly one message per event. Controlled FAKE model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.conversation import ConversationService
from runtime.notifications.outbox import OutboxDispatcher
from tests.conftest import World
from tests.integration.test_agent_loop import DOC_A, DOC_B, SPEC, build, decision, honest_policy, setup_task


def _conversation_task(world: World, tmp_path: Path, policy: object) -> tuple[object, str, str]:
    s = build(world, tmp_path, policy)  # type: ignore[arg-type]
    cs = ConversationService(world.conn, world.clock, s.runner.broker, None)
    conv = cs.current(world.employee.id)
    tid = setup_task(s, tmp_path, DOC_A, DOC_B, conversation_id=conv)
    return s, tid, conv


def _messages(world: World, conv: str, kind: str) -> list[str]:
    return [
        r[0]
        for r in world.conn.execute(
            "SELECT content FROM messages WHERE conversation_id = ? AND kind = ? ORDER BY rowid", (conv, kind)
        )
    ]


def test_question_survives_a_failed_delivery_and_arrives_once(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, tid, conv = _conversation_task(
        world, tmp_path, lambda t, p: decision("ask_owner", question="Qual prazo maximo?")
    )

    def broken(self: OutboxDispatcher, *a: object, **kw: object) -> int:
        raise OSError("delivery failed")

    monkeypatch.setattr(OutboxDispatcher, "deliver_pending", broken)
    out = s.runner.run(tid, SPEC)  # type: ignore[attr-defined]
    assert out.state == "WAITING_USER"
    assert _messages(world, conv, "question") == []  # before the fix: this question was gone for good
    pending = world.conn.execute(
        "SELECT kind, status, content FROM notification_outbox WHERE task_id = ?", (tid,)
    ).fetchall()
    assert [(r[0], r[1]) for r in pending] == [("question", "PENDING")]

    monkeypatch.undo()  # "restart": the dispatcher runs again
    d = OutboxDispatcher(world.conn, world.clock)
    assert d.deliver_pending() == 1
    assert d.deliver_pending() == 0  # repeated delivery never duplicates
    assert _messages(world, conv, "question") == ["Qual prazo maximo?"]
    msg_task = world.conn.execute("SELECT task_id FROM messages WHERE kind = 'question'").fetchone()[0]
    assert msg_task == tid


def test_state_and_notification_are_one_commit(world: World, tmp_path: Path) -> None:
    s, tid, _ = _conversation_task(world, tmp_path, honest_policy)
    out = s.runner.run(tid, SPEC)  # type: ignore[attr-defined]
    assert out.state == "COMPLETED"
    row = world.conn.execute(
        "SELECT o.kind, o.status, o.artifact_id, m.kind FROM notification_outbox o"
        " JOIN messages m ON m.id = o.message_id WHERE o.task_id = ?",
        (tid,),
    ).fetchone()
    assert (
        row[0] == "result" and row[1] == "DELIVERED" and row[2] == out.deliverable_id and row[3] == "result"
    )
    # every state that waits for the owner has its notification committed with it
    orphan = world.conn.execute(
        "SELECT COUNT(*) FROM tasks t WHERE t.state IN ('WAITING_USER','COMPLETED') AND NOT EXISTS"
        " (SELECT 1 FROM notification_outbox o WHERE o.task_id = t.id)"
    ).fetchone()[0]
    assert orphan == 0


def test_rollback_of_the_state_change_drops_the_notification(world: World, tmp_path: Path) -> None:
    from runtime.tasks.state_machine import TaskState
    from shared.errors import AtlasError

    s, tid, _ = _conversation_task(world, tmp_path, honest_policy)
    s.runner._prepare(tid)  # type: ignore[attr-defined]
    lease = s.tasks.acquire_lease(tid, "w1")  # type: ignore[attr-defined]
    s.tasks.pause(tid, actor=world.owner, expected_version=s.tasks.get(tid)["version"])  # type: ignore[attr-defined]
    with pytest.raises(AtlasError):  # the lease was revoked: the transition AND its notice are refused
        s.tasks.release(lease, TaskState.WAITING_USER, "q", notice=("question", "orfa?", None))  # type: ignore[attr-defined]
    assert world.conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0
