"""A3-06: an incomplete structured answer must never kill the worker or leave health green without one.

Controlled FAKE model (no network). The model output is validated against the complete decision schema
before any field is read; an unexpected internal error in the worker is visible, releases the task for
recovery and makes health report the executor as failed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.daemon import Core
from core.health import WorkerMonitor
from core.service import CoreService
from runtime.agent.loop import AgentRunner
from runtime.tasks.state_machine import TaskState
from tests.conftest import World
from tests.integration.test_agent_loop import DOC_A, DOC_B, SPEC, build, setup_task
from tests.integration.test_alpha2 import configure_intelligence, send
from tests.integration.test_openai_adapter import ok_body

MALFORMED: list[Any] = [
    [],  # a list, not an object
    {"decision": "finish"},  # required fields missing
    {
        "decision": "tool",
        "summary": None,
        "tool_id": "memory.search",
        "input_json": "{}",
        "artifact_id": "",
        "question": "",
    },
    {
        "decision": "tool",
        "summary": 42,
        "tool_id": "memory.search",
        "input_json": "{}",
        "artifact_id": "",
        "question": "",
    },
    {
        "decision": "tool",
        "summary": ["x"],
        "tool_id": "memory.search",
        "input_json": "{}",
        "artifact_id": "",
        "question": "",
    },
    {
        "decision": "ask_owner",
        "summary": "s",
        "tool_id": "",
        "input_json": "{}",
        "artifact_id": "",
        "question": 7,
    },
    {
        "decision": "explode",
        "summary": "s",
        "tool_id": "",
        "input_json": "{}",
        "artifact_id": "",
        "question": "",
    },
    {
        "decision": "finish",
        "summary": "s",
        "tool_id": "",
        "input_json": "{}",
        "artifact_id": "",
        "question": "",
        "extra": "field",
    },
]


@pytest.mark.parametrize("payload", MALFORMED, ids=[f"case{i}" for i in range(len(MALFORMED))])
def test_malformed_decision_is_rejected_before_any_field_is_used(
    world: World, tmp_path: Path, payload: Any
) -> None:
    s = build(world, tmp_path, lambda turn, prompt: json.dumps(payload))
    tid = setup_task(s, tmp_path, DOC_A, DOC_B)
    out = s.runner.run(tid, SPEC)  # before the fix: TypeError/AttributeError escaped and killed the worker
    assert out.state == TaskState.BLOCKED and out.reason
    assert s.tasks.get(tid)["blocked_reason"] == "NO_PROGRESS"
    assert world.conn.execute("SELECT COUNT(*) FROM actions WHERE task_id = ?", (tid,)).fetchone()[0] == 0
    rejected = [p for p in s.model.prompts[1:] if "rejected" in p]
    assert rejected, "the schema violation must be fed back to the model as a rejection"


def test_unexpected_worker_error_is_visible_and_recoverable(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bug inside one run must not end the worker thread silently nor leave the task RUNNING."""
    s = build(world, tmp_path, lambda turn, prompt: "{}")
    tid = setup_task(s, tmp_path, DOC_A, DOC_B)
    monitor = WorkerMonitor(world.clock)
    monitor.started()

    def boom(self: AgentRunner, task_id: str, spec: Any) -> Any:
        self._prepare(task_id)
        self.tasks.acquire_lease(task_id, self.worker_id)  # the crash happens mid-run, holding a lease
        raise RuntimeError("synthetic bug")

    monkeypatch.setattr(AgentRunner, "run", boom)
    Core.run_one(s.runner, tid, SPEC, monitor, s.tasks)  # the worker's per-task guard
    assert monitor.snapshot()["state"] == "degraded"
    assert "RuntimeError" in (monitor.snapshot()["last_error"] or "")
    task = s.tasks.get(tid)
    # lease revoked (fencing bumped); retried after backoff, bounded by the transient-retry limit
    assert task["state"] == TaskState.RETRYING and task["version"] > 1
    events = [r[0] for r in world.conn.execute("SELECT type FROM journal_events WHERE task_id = ?", (tid,))]
    assert "worker.error" in events


def test_health_is_not_green_without_a_live_worker(world: World) -> None:
    monitor = WorkerMonitor(world.clock)
    svc = CoreService(world.conn, world.clock, _broker(world), worker=monitor)
    from core.ipc.sessions import Session

    session = Session(world.owner, world.employee.id)
    h = svc.handle(session, _req("system.health"))["result"]
    assert h["components"]["worker"] == "not_started"
    assert h["status"] != "ok"
    monitor.started()
    monitor.beat()
    assert svc.handle(session, _req("system.health"))["result"]["components"]["worker"] == "ok"
    monitor.stopped("RuntimeError: synthetic")
    h = svc.handle(session, _req("system.health"))["result"]
    assert h["components"]["worker"] == "stopped" and h["status"] != "ok"
    world.clock.advance(seconds=1)
    monitor.started()
    monitor.beat()
    world.clock.advance(seconds=monitor.stale_after_s + 1)  # alive thread but no progress beat
    assert svc.handle(session, _req("system.health"))["result"]["components"]["worker"] == "stale"


def _broker(world: World) -> Any:
    from runtime.tools.registry import ToolRegistry
    from security.broker.broker import Broker
    from security.budget.budget import BudgetLimits, BudgetManager
    from security.policy.engine import PolicyEngine

    return Broker(
        world.conn,
        world.clock,
        registry=ToolRegistry(world.conn, world.clock),
        policy=PolicyEngine(),
        budget=BudgetManager(world.conn, world.clock, BudgetLimits("USD", None, None)),
    )


def _req(method: str, **params: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "req-00000001",
        "method": method,
        "params": {"schema_version": "1.0", "correlation_id": "corr-0001", **params},
    }


# ------------------------------------------------------------------ conversation path (same contract)


@pytest.mark.parametrize(
    "text",
    ["[]", '{"intent": "chat"}', '{"intent": "chat", "reply": null, "objective": ""}', '{"intent": 5}'],
)
def test_malformed_chat_decision_gets_an_honest_reply(env: Any, api: Any, text: str) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = c.call("conversations.current")["result"]["conversation_id"]
    api.queue.append((200, {}, ok_body(text=text)))
    out = send(c, env, conv, "Oi, como vai?")  # before the fix: AttributeError -> INTERNAL_ERROR, no reply
    assert out["intent"] == "chat_error" and out["task_id"] is None
    assert "Nada foi executado" in out["reply"]["content"]
