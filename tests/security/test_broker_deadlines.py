"""Review finding R-03: tool deadlines, cancellation, late completion and restart (spec 9.4, 12.2, 12.3).

Separates two things the review asked to prove independently:
* stopping NEW dispatches (lease/fencing - see test_broker.py::test_stop_all_blocks_next_dispatch), and
* handling the operation ALREADY in flight (this file).
"""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from runtime.tools.registry import RegistryError, ToolManifest, ToolRegistry
from security.broker.broker import AdapterOutcome, Broker
from security.budget.budget import BudgetLimits, BudgetManager
from security.policy.engine import PolicyEngine
from shared.errors import AtlasError, ErrorCode
from storage.store import open_store
from tests.conftest import World
from tests.control_plane import OWNER_CHANNEL, ControlPlane
from tests.fakes import process_adapters
from tests.fakes.adapters import OWNER_SEND, WORKSPACE_WRITE, closed

GRACE = 0.2
SEND = dataclasses.replace(OWNER_SEND, tool_id="messaging.send_owner_slow", timeout_s=1)
READ = ToolManifest(
    tool_id="research.slow_lookup",
    version="1.0.0",
    description="FAKE slow read-only lookup",
    input_schema=closed({"q": {"type": "string"}}),
    effect_class="READ_ONLY",
    base_risk="R0",
    timeout_s=1,
)
PROC_READ = dataclasses.replace(
    WORKSPACE_WRITE,
    tool_id="sandbox.run_script",
    effect_class="READ_ONLY",
    base_risk="R0",
    isolation="process",
    timeout_s=1,
)
PROC_WRITE = dataclasses.replace(
    WORKSPACE_WRITE, tool_id="sandbox.write_outside", isolation="process", timeout_s=1
)


class Scenario:
    """A fake external system whose behaviour each test scripts. Records every real effect."""

    def __init__(self) -> None:
        self.effects: list[str] = []
        self.release = threading.Event()
        self.calls = 0
        self.mode = "hang_ignoring_cancel"

    def adapter(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        self.calls += 1
        if self.mode == "hang_ignoring_cancel":  # e.g. socket stuck; effect status unknown
            self.release.wait(10)
            self.effects.append("sent")
            return AdapterOutcome("SUCCEEDED", external_reference="late-receipt-1")
        if self.mode == "cooperative_before_send":  # honours cancellation before touching the world
            while not ctx.cancelled:
                time.sleep(0.01)
            return AdapterOutcome("FAILED", error_message="cancelled before sending")
        if self.mode == "sent_then_lost":  # effect happened, response never comes back
            self.effects.append("sent")
            self.release.wait(10)
            return AdapterOutcome("UNKNOWN", error_message="connection lost after submit")
        raise AssertionError(self.mode)


def build(world: World, scenario: Scenario) -> ControlPlane:
    reg = ToolRegistry(world.conn, world.clock)
    for m, fn in (
        (SEND, scenario.adapter),
        (READ, scenario.adapter),
        (PROC_READ, process_adapters.sleep_forever),
        (PROC_WRITE, process_adapters.write_marker_then_hang),
    ):
        reg.register(m, fn)
        reg.enable(m.tool_id, m.version, actor=world.owner, validation_evidence="deadline tests")
    broker = Broker(
        world.conn,
        world.clock,
        registry=reg,
        policy=PolicyEngine(),
        budget=BudgetManager(world.conn, world.clock, BudgetLimits("USD", 10_000, 5_000)),
        owner_channels=frozenset({OWNER_CHANNEL}),
        grace_s=GRACE,
    )
    return ControlPlane(world, broker, broker.tasks, reg, None)  # type: ignore[arg-type]


def send(cp: ControlPlane, tid: str) -> dict[str, Any]:
    return cp.proposal(tid, SEND.tool_id, {"recipient_ref": OWNER_CHANNEL, "message": "relatorio"})


@pytest.fixture
def sc() -> Scenario:
    s = Scenario()
    yield s
    s.release.set()  # never leave threads hanging after a test


def test_adapter_that_never_returns_is_bounded_and_unknown(world: World, sc: Scenario) -> None:
    cp = build(world, sc)
    tid = cp.ready_task()
    t0 = time.monotonic()
    res = cp.broker.submit(send(cp, tid), cp.lease(tid))
    elapsed = time.monotonic() - t0
    assert elapsed < SEND.timeout_s + GRACE + 1.0, f"broker blocked {elapsed:.2f}s"
    assert res.status == "UNKNOWN"  # an external effect may have happened
    assert "DEADLINE_EXCEEDED" in res.reason
    assert cp.tasks.get(tid)["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN"
    row = world.conn.execute("SELECT status FROM actions WHERE id=?", (res.action_id,)).fetchone()
    assert row[0] == "UNKNOWN"


def test_timeout_before_effect_is_a_proven_failure(world: World, sc: Scenario) -> None:
    sc.mode = "cooperative_before_send"
    cp = build(world, sc)
    tid = cp.ready_task()
    res = cp.broker.submit(send(cp, tid), cp.lease(tid))
    assert res.status == "FAILED"  # the trusted adapter acknowledged cancellation before sending
    assert sc.effects == []
    assert cp.tasks.get(tid)["state"] == "RUNNING"  # no uncertainty, worker may replan


def test_late_completion_is_recorded_without_reenabling_the_worker(world: World, sc: Scenario) -> None:
    cp = build(world, sc)
    tid = cp.ready_task()
    lease = cp.lease(tid)
    res = cp.broker.submit(send(cp, tid), lease)
    assert res.status == "UNKNOWN"
    sc.release.set()  # the stuck call finally completes and reports a receipt
    deadline = time.monotonic() + 3
    got: list[tuple[str, str]] = []
    while not got and time.monotonic() < deadline:
        got = cp.broker.collect_late_results()
        time.sleep(0.02)
    assert got == [(res.action_id, "CONFIRMED")]
    assert sc.effects == ["sent"]
    # The old worker cannot continue: its lease died when the task left RUNNING.
    with pytest.raises(AtlasError) as e:
        cp.broker.submit(send(cp, tid), lease)
    assert e.value.code == ErrorCode.UNAUTHORIZED
    assert cp.tasks.get(tid)["state"] == "READY"  # next step needs a fresh lease and policy check


def test_late_completion_after_owner_cancel_is_recorded_but_task_stays_cancelled(
    world: World, sc: Scenario
) -> None:
    cp = build(world, sc)
    tid = cp.ready_task()
    res = cp.broker.submit(send(cp, tid), cp.lease(tid))
    cp.tasks.cancel(tid, actor=world.owner, expected_version=cp.tasks.get(tid)["version"])
    sc.release.set()
    for _ in range(150):
        if cp.broker.collect_late_results():
            break
        time.sleep(0.02)
    status = world.conn.execute("SELECT status FROM actions WHERE id=?", (res.action_id,)).fetchone()[0]
    assert status == "CONFIRMED"  # the real result is recorded...
    assert cp.tasks.get(tid)["state"] == "CANCELLED"  # ...but nothing resumes


def test_response_lost_after_effect_then_restart_never_duplicates(world: World, sc: Scenario) -> None:
    sc.mode = "sent_then_lost"
    cp = build(world, sc)
    tid = cp.ready_task()
    prop = send(cp, tid)
    res = cp.broker.submit(prop, cp.lease(tid))
    assert res.status == "UNKNOWN"
    assert sc.effects == ["sent"]
    # Process dies: late-result queue is lost. A new core starts on the same database.
    world.conn.close()
    world.conn = open_store(world.path, world.clock)
    cp2 = build(world, sc)
    rep = cp2.tasks.recover_after_restart()
    assert tid not in rep.tasks_ready
    with pytest.raises(AtlasError):
        cp2.broker.submit(prop, cp2.lease(tid, "w-after-restart"))
    assert sc.calls == 1 and sc.effects == ["sent"]
    final = cp2.broker.reconcile(
        res.action_id,
        actor=world.owner,
        happened=True,  # type: ignore[arg-type]
        evidence="mensagem sintetica encontrada no canal do proprietario",
    )
    assert final == "CONFIRMED"
    assert sc.calls == 1


def test_owner_cancel_reaches_operation_in_flight(world: World, sc: Scenario) -> None:
    sc.mode = "cooperative_before_send"
    long_send = dataclasses.replace(SEND, tool_id="messaging.send_owner_long", timeout_s=30)
    cp = build(world, sc)
    cp.registry.register(long_send, sc.adapter)
    cp.registry.enable(long_send.tool_id, "1.0.0", actor=world.owner, validation_evidence="t")
    tid = cp.ready_task()
    lease = cp.lease(tid)
    hits: list[list[str]] = []
    threading.Timer(0.3, lambda: hits.append(cp.broker.request_cancel(tid))).start()
    t0 = time.monotonic()
    res = cp.broker.submit(
        cp.proposal(tid, long_send.tool_id, {"recipient_ref": OWNER_CHANNEL, "message": "x"}), lease
    )
    assert time.monotonic() - t0 < 5  # far below the 30 s deadline
    assert hits == [[res.action_id]]
    assert res.status == "FAILED" and sc.effects == []


def test_read_only_timeout_is_retryable_failure(world: World, sc: Scenario) -> None:
    cp = build(world, sc)
    tid = cp.ready_task(external_writes=False)
    res = cp.broker.submit(cp.proposal(tid, READ.tool_id, {"q": "precos"}), cp.lease(tid))
    assert res.status == "FAILED"
    assert res.tool_result is not None and res.tool_result["retry_class"] == "TRANSIENT"


def test_process_isolation_really_stops_the_operation(world: World, sc: Scenario, tmp_path: Path) -> None:
    cp = build(world, sc)
    tid = cp.ready_task(external_writes=False)
    t0 = time.monotonic()
    res = cp.broker.submit(cp.proposal(tid, PROC_READ.tool_id, {"path": "x", "content": "y"}), cp.lease(tid))
    assert time.monotonic() - t0 < PROC_READ.timeout_s + 4
    assert res.status == "FAILED" and "terminated" in res.reason


def test_process_tool_killed_after_possible_effect_is_unknown(
    world: World, sc: Scenario, tmp_path: Path
) -> None:
    cp = build(world, sc)
    tid = cp.ready_task()
    marker = tmp_path / "marker.txt"
    res = cp.broker.submit(
        cp.proposal(tid, PROC_WRITE.tool_id, {"path": str(marker), "content": "y"}), cp.lease(tid)
    )
    assert res.status == "UNKNOWN"  # killed, but it may already have acted
    assert marker.read_text(encoding="utf-8") == "effect happened"


def test_process_tools_cannot_receive_credentials(world: World) -> None:
    bad = dataclasses.replace(PROC_WRITE, credential_purpose="email_send")
    with pytest.raises(RegistryError, match="never receive credentials"):
        ToolRegistry(world.conn, world.clock).register(bad, process_adapters.quick)
