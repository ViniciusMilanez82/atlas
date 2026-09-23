"""AT-010.5 (limits, backoff, circuit breaker) and AT-010.6 (scheduled jobs)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from runtime.tasks.engine import TaskEngine
from runtime.tasks.limits import (
    AttemptLimits,
    BreakerState,
    CircuitBreaker,
    ProgressGuard,
    StepOutcome,
    backoff_delay,
)
from runtime.tasks.scheduler import Scheduler, next_local_occurrence
from runtime.tasks.state_machine import TaskState
from shared.actors import Actor
from shared.clock import ManualClock
from shared.errors import AtlasError
from tests.conftest import World

S = TaskState


@pytest.fixture
def engine(world: World) -> TaskEngine:
    return TaskEngine(world.conn, world.clock)


def running(engine: TaskEngine, world: World, worker: str = "w1"):  # type: ignore[no-untyped-def]
    tid = engine.create(world.owner, employee_id=world.employee.id, objective="x")
    for to in (S.UNDERSTANDING, S.PLANNING, S.READY):
        engine.transition(
            tid, to, expected_version=engine.get(tid)["version"], actor=Actor("runtime", "rt"), reason="t"
        )
    return engine.acquire_lease(tid, worker)


class TestLimits:
    def test_bounds_are_enforced(self) -> None:
        with pytest.raises(ValueError):
            AttemptLimits(max_transient_retries=50)
        with pytest.raises(ValueError):
            AttemptLimits(max_steps_without_verified_result=0)

    def test_backoff_has_jitter_and_cap(self) -> None:
        lim = AttemptLimits()
        rng = random.Random(7)
        delays = [backoff_delay(10, lim, rng).total_seconds() for _ in range(200)]
        assert max(delays) <= lim.backoff_cap_s
        assert len({round(d, 3) for d in delays}) > 150  # jittered, not constant

    def test_transient_failures_retry_then_block(self, engine: TaskEngine, world: World) -> None:
        guard = ProgressGuard(engine, rng=random.Random(1))
        lease = running(engine, world)
        for attempt in range(1, 4):
            assert guard.record(lease, StepOutcome.TRANSIENT_FAILURE) == S.RETRYING
            assert guard.promote_due_retries() == []  # backoff not elapsed yet (unless jitter ~0)
            world.clock.advance(seconds=61)
            assert guard.promote_due_retries() == [lease.task_id]
            lease = engine.acquire_lease(lease.task_id, f"w{attempt + 1}")
        assert guard.record(lease, StepOutcome.TRANSIENT_FAILURE) == S.BLOCKED
        assert engine.get(lease.task_id)["blocked_reason"] == "RETRY_LIMIT"

    def test_twenty_steps_without_result_blocks(self, engine: TaskEngine, world: World) -> None:
        guard = ProgressGuard(engine)
        lease = running(engine, world)
        for _ in range(19):
            assert guard.record(lease, StepOutcome.NO_NEW_RESULT) == S.RUNNING
        assert guard.record(lease, StepOutcome.NO_NEW_RESULT) == S.BLOCKED
        assert engine.get(lease.task_id)["blocked_reason"] == "NO_PROGRESS"

    def test_verified_result_resets_counters(self, engine: TaskEngine, world: World) -> None:
        guard = ProgressGuard(engine)
        lease = running(engine, world)
        for _ in range(15):
            guard.record(lease, StepOutcome.NO_NEW_RESULT)
        guard.record(lease, StepOutcome.VERIFIED_RESULT)
        for _ in range(15):
            assert guard.record(lease, StepOutcome.NO_NEW_RESULT) == S.RUNNING

    def test_replans_without_progress_block(self, engine: TaskEngine, world: World) -> None:
        guard = ProgressGuard(engine)
        lease = running(engine, world)
        assert guard.record(lease, StepOutcome.REPLANNED_WITHOUT_PROGRESS) == S.RUNNING
        assert guard.record(lease, StepOutcome.REPLANNED_WITHOUT_PROGRESS) == S.RUNNING
        assert guard.record(lease, StepOutcome.REPLANNED_WITHOUT_PROGRESS) == S.BLOCKED

    def test_stale_lease_cannot_record(self, engine: TaskEngine, world: World) -> None:
        guard = ProgressGuard(engine)
        lease = running(engine, world)
        engine.pause(lease.task_id, actor=world.owner, expected_version=engine.get(lease.task_id)["version"])
        with pytest.raises(AtlasError):
            guard.record(lease, StepOutcome.NO_NEW_RESULT)


class TestCircuitBreaker:
    def test_opens_probes_and_closes(self) -> None:
        clock = ManualClock()
        cb = CircuitBreaker(clock, failure_threshold=3, cooldown=timedelta(seconds=30))
        for _ in range(3):
            cb.guard()
            cb.failure()
        assert cb.state == BreakerState.OPEN
        with pytest.raises(AtlasError):
            cb.guard()
        clock.advance(seconds=31)
        cb.guard()  # half-open probe allowed
        assert cb.state == BreakerState.HALF_OPEN
        cb.failure()
        assert cb.state == BreakerState.OPEN
        clock.advance(seconds=31)
        cb.guard()
        cb.success()
        assert cb.state == BreakerState.CLOSED


class TestScheduler:
    def test_daily_local_time_respects_dst(self) -> None:
        # New York: DST ends 2026-11-01. 08:00 local is 12:00Z before and 13:00Z after.
        before = datetime(2026, 10, 31, 13, 0, tzinfo=UTC)
        first = next_local_occurrence(before, "08:00", "America/New_York")
        assert first == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)
        prev = next_local_occurrence(datetime(2026, 10, 30, 11, 0, tzinfo=UTC), "08:00", "America/New_York")
        assert prev == datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

    def test_sao_paulo_default(self) -> None:
        after = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)  # 09:00 in Sao Paulo (UTC-3)
        nxt = next_local_occurrence(after, "08:30", "America/Sao_Paulo")
        assert nxt == datetime(2026, 9, 24, 11, 30, tzinfo=UTC)

    def test_runs_once_per_occurrence_and_dedups(self, engine: TaskEngine, world: World) -> None:
        sch = Scheduler(engine)
        sch.create_job(
            actor=world.owner,
            employee_id=world.employee.id,
            objective="Resumo diario",
            timezone="America/Sao_Paulo",
            dedup_key="daily-summary",
            interval_minutes=60,
        )
        assert sch.run_due() == []
        world.clock.advance(minutes=61)
        first = sch.run_due()
        assert len(first) == 1 and first[0].task_id is not None and first[0].missed_count == 0
        assert sch.run_due() == []  # same occurrence never twice

    def test_missed_occurrences_are_consolidated_and_confirmed(
        self, engine: TaskEngine, world: World
    ) -> None:
        sch = Scheduler(engine)
        sch.create_job(
            actor=world.owner,
            employee_id=world.employee.id,
            objective="Enviar relatorio ao cliente",
            timezone="America/Sao_Paulo",
            dedup_key="client-report",
            interval_minutes=60,
            external_writes=True,
        )
        world.clock.advance(hours=5, minutes=1)  # Mac was off: 5 occurrences due
        runs = sch.run_due()
        assert len(runs) == 1
        assert runs[0].missed_count == 4
        assert runs[0].needs_confirmation is True
        task = engine.get(runs[0].task_id)  # type: ignore[arg-type]
        assert task["state"] == "WAITING_USER"
        assert "4 missed" in task["objective"]
        n_tasks = world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert n_tasks == 1

    def test_skip_policy_does_not_create_for_missed(self, engine: TaskEngine, world: World) -> None:
        sch = Scheduler(engine)
        sch.create_job(
            actor=world.owner,
            employee_id=world.employee.id,
            objective="x",
            timezone="UTC",
            dedup_key="skip-job",
            interval_minutes=30,
            missed_policy="SKIP",
        )
        world.clock.advance(hours=3)
        runs = sch.run_due()
        assert runs[0].task_id is None and runs[0].missed_count > 0

    def test_validation(self, engine: TaskEngine, world: World) -> None:
        sch = Scheduler(engine)
        kwargs = {"employee_id": world.employee.id, "objective": "x", "dedup_key": "k"}
        with pytest.raises(AtlasError):
            sch.create_job(actor=world.owner, timezone="Mars/Olympus", interval_minutes=5, **kwargs)
        with pytest.raises(AtlasError):
            sch.create_job(actor=world.owner, timezone="UTC", **kwargs)
        with pytest.raises(AtlasError):
            sch.create_job(actor=Actor("runtime", "rt"), timezone="UTC", interval_minutes=5, **kwargs)
