"""A3-03 / T19: a correction sent while the task runs changes the NEXT step, and a stale proposal
decided before the correction is never dispatched.

Controlled FAKE model (no network). The correction arrives through another connection while the
worker is blocked between the model's decision and the broker dispatch.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.conversation import ConversationService
from runtime.tools.builtin import BuiltinTools
from runtime.tools.registry import ToolRegistry
from security.broker.broker import Broker
from security.budget.budget import BudgetLimits, BudgetManager
from security.policy.engine import PolicyEngine
from shared.ids import new_id
from storage.db import transaction
from storage.store import open_store
from tests.conftest import World
from tests.integration.test_agent_loop import DOC_A, DOC_B, SPEC, UUID, build, decision, setup_task

CORRECTION = "Na verdade, priorize prazo de entrega em vez de preco."


def side_conversation(world: World, tmp_path: Path) -> ConversationService:
    """What another IPC connection sees: its own SQLite connection and broker."""
    conn = open_store(world.path, world.clock)
    reg = ToolRegistry(conn, world.clock)
    BuiltinTools(world.path, tmp_path / "store", world.clock).register(reg, enabled_by=world.owner)
    broker = Broker(
        conn,
        world.clock,
        registry=reg,
        policy=PolicyEngine(),
        budget=BudgetManager(conn, world.clock, BudgetLimits("USD", 100_000, 50_000)),
    )
    return ConversationService(conn, world.clock, broker, None)


def conversation_for(world: World, task_id: str) -> str:
    cid = new_id()
    with transaction(world.conn):
        world.conn.execute(
            "INSERT INTO conversations(id, employee_id, created_at) VALUES (?,?,?)",
            (cid, world.employee.id, "2026-01-01T00:00:00.000Z"),
        )
        world.conn.execute("UPDATE tasks SET conversation_id = ? WHERE id = ?", (cid, task_id))
    return cid


def report(criterion: str, ids: list[str]) -> str:
    return (
        f"# Comparacao ({criterion})\n\nFornecedor Alfa: R$ 1.000/mes, 10 dias. Fornecedor Beta: R$ 900/mes, "
        f"25 dias.\n\nRecomendacao por {criterion}: "
        + ("Fornecedor Alfa." if criterion == "prazo" else "Fornecedor Beta.")
        + f"\n\nFontes: artifact:{ids[0]} e artifact:{ids[1]}\n"
    )


def test_correction_between_decision_and_dispatch(world: World, tmp_path: Path) -> None:
    state: dict[str, Any] = {}

    def policy(turn: int, prompt: str) -> str:
        ids = re.findall(rf"artifact_id ({UUID})", prompt)
        state.setdefault("ids", ids)
        if turn == 1:
            return decision(
                "tool", tool="artifact.read_text", inp={"artifact_id": ids[0]}, summary="ler alfa"
            )
        if turn == 2:
            return decision(
                "tool", tool="artifact.read_text", inp={"artifact_id": ids[1]}, summary="ler beta"
            )
        if turn == 3:
            # The model already decided (by price). Before the broker sees it, the owner corrects.
            out = state["side"].handle(
                world.owner,
                world.employee.id,
                {"conversation_id": state["cid"], "client_message_id": new_id(), "text": CORRECTION},
            )
            state["ack"] = out
            return decision(
                "tool",
                tool="artifact.write_text",
                inp={"name": "relatorio.md", "content": report("preco", state["ids"])},
                summary="relatorio por preco",
            )
        state.setdefault("prompts_after", []).append(prompt)
        if turn == 4:
            criterion = "prazo" if "priorize prazo" in prompt else "preco"
            return decision(
                "tool",
                tool="artifact.write_text",
                inp={"name": "relatorio.md", "content": report(criterion, state["ids"])},
                summary=f"relatorio por {criterion}",
            )
        written = re.findall(rf'"artifact_id": "({UUID})", "name": "relatorio.md"', prompt)
        return decision("finish", artifact=written[-1], summary="entregar")

    s = build(world, tmp_path, policy)
    tid = setup_task(s, tmp_path, DOC_A, DOC_B)
    state["cid"] = conversation_for(world, tid)
    state["side"] = side_conversation(world, tmp_path)
    out = s.runner.run(tid, SPEC)

    ack = state["ack"]
    assert ack["intent"] == "correction" and ack["task_id"] == tid  # same task, no new task_id
    assert world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert "revisão 2" in ack["reply"]["content"]  # acknowledged only after it was durably recorded
    writes = world.conn.execute(
        "SELECT input_json FROM actions WHERE task_id = ? AND tool_id = 'artifact.write_text'", (tid,)
    ).fetchall()
    assert len(writes) == 1 and "por prazo" in writes[0][0]  # the stale price report never dispatched
    assert "CURRENT" in state["prompts_after"][0] and "priorize prazo" in state["prompts_after"][0]
    reads = world.conn.execute(
        "SELECT COUNT(*) FROM actions WHERE task_id = ? AND tool_id = 'artifact.read_text' AND status = 'CONFIRMED'"
        " AND instr(input_json, ?) > 0",
        (tid, state["ids"][0]),
    ).fetchone()[0]
    assert reads == 1  # the effect confirmed before the correction is kept, not repeated
    assert out.state == "COMPLETED", (out.reason, out.gaps)
    revs = world.conn.execute(
        "SELECT revision, kind, instruction FROM task_instruction_versions WHERE task_id = ? ORDER BY revision",
        (tid,),
    ).fetchall()
    assert [(r[0], r[1]) for r in revs] == [(1, "ORIGINAL"), (2, "CORRECTION")]
    assert revs[1][2] == CORRECTION  # the owner's words, not a model summary


def test_ambiguous_correction_asks_which_task(world: World, tmp_path: Path) -> None:
    s = build(world, tmp_path, lambda t, p: decision("ask_owner", question="?"))
    t1 = setup_task(s, tmp_path, DOC_A, DOC_B)
    t2 = s.tasks.create(
        world.owner, employee_id=world.employee.id, objective="Outra tarefa", criteria=[("x", True)]
    )
    cid = conversation_for(world, t1)
    with transaction(world.conn):
        world.conn.execute("UPDATE tasks SET conversation_id = ? WHERE id = ?", (cid, t2))
    side = side_conversation(world, tmp_path)
    out = side.handle(
        world.owner,
        world.employee.id,
        {"conversation_id": cid, "client_message_id": new_id(), "text": CORRECTION},
    )
    assert out["intent"] == "correction_ambiguous" and out["task_id"] is None
    assert "Outra tarefa" in out["reply"]["content"]
    assert s.tasks.get(t1)["instruction_revision"] == 1 and s.tasks.get(t2)["instruction_revision"] == 1
    # the owner points at the task explicitly: the correction reaches exactly that one
    out = side.handle(
        world.owner,
        world.employee.id,
        {"conversation_id": cid, "client_message_id": new_id(), "text": CORRECTION, "task_id": t2},
    )
    assert out["intent"] == "correction" and out["task_id"] == t2
    assert s.tasks.get(t2)["instruction_revision"] == 2 and s.tasks.get(t1)["instruction_revision"] == 1


def test_material_correction_revokes_pending_approval(cp: Any) -> None:
    tid = cp.ready_task()
    lease = cp.lease(tid)
    res = cp.broker.submit(
        cp.proposal(tid, "email.send_external", {"to": "cliente@example.test", "subject": "s", "body": "b"}),
        lease,
    )
    assert res.status == "APPROVAL_REQUIRED"
    rev = cp.tasks.update_instruction(tid, actor=cp.world.owner, text="Mande so amanha", kind="CORRECTION")
    assert rev == 2
    ap = cp.broker.approvals.get(res.approval["approval_id"])
    assert ap["status"] == "REVOKED"  # an approval given for the old instruction does not survive
