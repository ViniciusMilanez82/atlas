"""A3-05: a valid long model call must not lose its lease; a lost worker must not leave RUNNING behind.

Injectable clock + controlled FAKE model (no network). The lease is renewed by an independent keeper
(own thread, own database connection) while the worker blocks; a watchdog with its own connection
reclaims expired leases, and scheduled jobs keep running while a long task is in progress.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from runtime.tasks.engine import DEFAULT_LEASE_TTL
from runtime.tasks.scheduler import Scheduler
from runtime.tasks.state_machine import TaskState
from runtime.tasks.watchdog import Watchdog, WatchdogReport
from shared.actors import Actor
from storage.store import open_store
from tests.conftest import World
from tests.integration.test_agent_loop import DOC_A, DOC_B, SPEC, build, honest_policy, setup_task


def _slow(world: World, total_s: int, step_s: int = 10) -> None:
    """A model call that lasts `total_s` of (injected) time, in steps that let the keeper beat."""
    for _ in range(total_s // step_s):
        world.clock.advance(seconds=step_s)
        time.sleep(0.08)


def test_long_inference_keeps_its_lease_and_finishes(world: World, tmp_path: Path) -> None:
    def policy(turn: int, prompt: str) -> str:
        if turn == 1:
            _slow(world, 3 * int(DEFAULT_LEASE_TTL.total_seconds()))  # 3x the TTL inside ONE call
        return honest_policy(turn, prompt)

    s = build(world, tmp_path, policy)
    s.runner.keeper_interval_s = 0.02
    tid = setup_task(s, tmp_path, DOC_A, DOC_B)
    out = s.runner.run(tid, SPEC)  # before the fix: the dispatch after the call hit a stale lease
    assert out.state == TaskState.COMPLETED, out.reason
    beats = world.conn.execute(
        "SELECT COUNT(*) FROM journal_events WHERE task_id = ? AND type = 'task.lease_renewed'", (tid,)
    ).fetchone()[0]
    assert beats == 0  # renewals are operational noise, not journal events
    assert s.runner.last_keeper_beats > 0


def test_stale_worker_cannot_dispatch_and_task_is_not_left_running(world: World, tmp_path: Path) -> None:
    s = build(world, tmp_path, honest_policy)
    tid = setup_task(s, tmp_path, DOC_A, DOC_B)
    s.runner._prepare(tid)
    lease = s.tasks.acquire_lease(tid, "worker-dead")  # its keeper died with it
    world.clock.advance(seconds=DEFAULT_LEASE_TTL.total_seconds() + 1)
    wd = Watchdog(open_store(world.path, world.clock), world.clock)  # independent connection
    report = wd.sweep()
    assert tid in report.reclaimed
    task = s.tasks.get(tid)
    assert task["state"] == TaskState.RETRYING  # never RUNNING without a live heartbeat
    proposal = {
        "schema_version": "1.0",
        "task_id": tid,
        "step_id": "00000000-0000-4000-8000-000000000001",
        "tool_id": "memory.search",
        "tool_version": "1.0.0",
        "input": {"query": "x"},
        "expected_outcome": "late",
        "verification": {"kind": "deterministic_check", "required": True},
        "instruction_revision": 1,
    }
    import pytest

    from shared.errors import AtlasError

    with pytest.raises(AtlasError):
        s.runner.broker.submit(proposal, lease)  # late answer of the stale worker
    assert world.conn.execute("SELECT COUNT(*) FROM actions WHERE task_id = ?", (tid,)).fetchone()[0] == 0


def test_expired_lease_with_uncertain_effect_is_blocked_not_retried(world: World, tmp_path: Path) -> None:
    s = build(world, tmp_path, honest_policy)
    tid = setup_task(s, tmp_path, DOC_A, DOC_B)
    s.runner._prepare(tid)
    s.tasks.acquire_lease(tid, "worker-dead")
    from storage.db import transaction
    from tests.helpers import insert_action

    with transaction(world.conn):
        insert_action(world.conn, tid, status="DISPATCHING")
    world.clock.advance(seconds=DEFAULT_LEASE_TTL.total_seconds() + 1)
    Watchdog(open_store(world.path, world.clock), world.clock).sweep()
    task = s.tasks.get(tid)
    assert task["state"] == TaskState.BLOCKED and task["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN"


def test_scheduler_is_not_stuck_behind_a_long_task(world: World, tmp_path: Path) -> None:
    reports: list[WatchdogReport] = []

    def sweep_elsewhere() -> None:  # the daemon's watchdog thread, with its own connection
        reports.append(Watchdog(open_store(world.path, world.clock), world.clock).sweep())

    def policy(turn: int, prompt: str) -> str:
        if turn == 1:  # the worker is blocked inside a model call while the watchdog runs
            t = threading.Thread(target=sweep_elsewhere)
            t.start()
            t.join(10)
        return honest_policy(turn, prompt)

    s = build(world, tmp_path, policy)
    tid = setup_task(s, tmp_path, DOC_A, DOC_B)
    Scheduler(s.tasks).create_job(
        actor=world.owner,
        employee_id=world.employee.id,
        objective="relatorio diario sintetico",
        timezone="America/Sao_Paulo",
        dedup_key="daily-report",
        interval_minutes=60,
    )
    world.clock.advance(minutes=61)
    out = s.runner.run(tid, SPEC)
    assert out.state == TaskState.COMPLETED
    assert len(reports) == 1 and len(reports[0].scheduled) == 1 and reports[0].scheduled[0].task_id
    assert tid not in reports[0].reclaimed  # the long task kept a live lease


def test_watchdog_actor_is_not_the_owner() -> None:
    assert Watchdog.ACTOR != Actor("owner", "x")
