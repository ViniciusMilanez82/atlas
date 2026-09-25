"""Attempt limits, backoff with jitter and circuit breaker (spec 9.4, AT-010.5).

Initial values from the spec: 3 retries per transient error, 2 plan revisions without material
progress, pause after 20 consecutive steps without a new verifiable result. They are configurable
only within safe bounds. No infinite click loops and no billing while waiting on CAPTCHA, login or
a human: exceeding a limit blocks the task with an explicit reason.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from runtime.notifications.outbox import Notice, enqueue_in_txn
from runtime.tasks.engine import Lease, TaskEngine
from runtime.tasks.state_machine import TaskState
from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from storage.db import require_transaction, transaction

SAFE_BOUNDS = {
    "max_transient_retries": (0, 5),
    "max_replans_without_progress": (0, 5),
    "max_steps_without_verified_result": (1, 50),
}


@dataclass(frozen=True)
class AttemptLimits:
    max_transient_retries: int = 3
    max_replans_without_progress: int = 2
    max_steps_without_verified_result: int = 20
    backoff_base_s: float = 2.0
    backoff_cap_s: float = 60.0

    def __post_init__(self) -> None:
        for name, (lo, hi) in SAFE_BOUNDS.items():
            value = getattr(self, name)
            if not lo <= value <= hi:
                raise ValueError(f"{name}={value} outside safe bounds [{lo}, {hi}]")


def backoff_delay(attempt: int, limits: AttemptLimits, rng: random.Random) -> timedelta:
    """Full-jitter exponential backoff: uniform(0, min(cap, base * 2**attempt))."""
    ceiling = min(limits.backoff_cap_s, limits.backoff_base_s * (2 ** max(attempt - 1, 0)))
    return timedelta(seconds=rng.uniform(0, ceiling))


class StepOutcome(StrEnum):
    VERIFIED_RESULT = "VERIFIED_RESULT"  # new verifiable result: counters reset
    NO_NEW_RESULT = "NO_NEW_RESULT"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    REPLANNED_WITHOUT_PROGRESS = "REPLANNED_WITHOUT_PROGRESS"


class ProgressGuard:
    def __init__(
        self, engine: TaskEngine, limits: AttemptLimits | None = None, rng: random.Random | None = None
    ) -> None:
        self.engine = engine
        self.conn: sqlite3.Connection = engine.conn
        self.clock: Clock = engine.clock
        self.limits = limits or AttemptLimits()
        self.rng = rng or random.Random()  # noqa: S311 - jitter, not security

    def _counters_in_txn(self, task_id: str) -> sqlite3.Row:
        require_transaction(self.conn)
        self.conn.execute(
            "INSERT OR IGNORE INTO task_progress(task_id, updated_at) VALUES (?, ?)",
            (task_id, to_utc_str(self.clock.now())),
        )
        row: sqlite3.Row = self.conn.execute(
            "SELECT * FROM task_progress WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row

    def record(self, lease: Lease, outcome: StepOutcome, notice: Notice | None = None) -> TaskState:
        """Record one step for the lease holder. Returns the task state afterwards. ``notice`` is queued
        for the owner in the same commit when the step makes the task leave RUNNING (A3-27)."""
        worker = Actor("worker", lease.worker_id, "internal")
        now = self.clock.now()
        with transaction(self.conn):
            task = self.engine.check_lease_in_txn(lease.task_id, lease.worker_id, lease.fencing_token)
            c = self._counters_in_txn(lease.task_id)
            fails, replans, steps = (
                c["transient_failures"],
                c["replans_without_progress"],
                c["steps_without_verified"],
            )
            if outcome == StepOutcome.VERIFIED_RESULT:
                fails, replans, steps = 0, 0, 0
            elif outcome == StepOutcome.NO_NEW_RESULT:
                steps += 1
            elif outcome == StepOutcome.TRANSIENT_FAILURE:
                fails += 1
                steps += 1
            elif outcome == StepOutcome.REPLANNED_WITHOUT_PROGRESS:
                replans += 1
            next_at: str | None = None
            target: TaskState | None = None
            reason: str | None = None
            if fails > self.limits.max_transient_retries:
                target, reason = TaskState.BLOCKED, "RETRY_LIMIT"
            elif (
                replans > self.limits.max_replans_without_progress
                or steps >= self.limits.max_steps_without_verified_result
            ):
                target, reason = TaskState.BLOCKED, "NO_PROGRESS"
            elif outcome == StepOutcome.TRANSIENT_FAILURE:
                next_at = to_utc_str(now + backoff_delay(fails, self.limits, self.rng))
                target = TaskState.RETRYING
            self.conn.execute(
                "UPDATE task_progress SET transient_failures = ?, replans_without_progress = ?,"
                " steps_without_verified = ?, next_attempt_at = ?, updated_at = ? WHERE task_id = ?",
                (fails, replans, steps, next_at, to_utc_str(now), lease.task_id),
            )
            if target is not None:
                self.engine.transition_in_txn(
                    task,
                    target,
                    worker,
                    f"limits: failures={fails} replans={replans} steps_without_result={steps}",
                    blocked_reason=reason,
                )
                if notice is not None and target == TaskState.BLOCKED:
                    enqueue_in_txn(
                        self.conn,
                        self.clock,
                        employee_id=task["employee_id"],
                        task_id=task["id"],
                        kind=notice[0],
                        content=notice[1],
                        artifact_id=notice[2],
                    )
                return target
            return TaskState.RUNNING

    def reclaim_after_worker_loss(self, task_id: str, why: str) -> TaskState | None:
        """Take a RUNNING task back from a worker that crashed or lost its lease (A3-05, A3-06).

        Leaving RUNNING bumps the fencing token, so the old worker can never dispatch again. Effects of
        uncertain outcome block the task for reconciliation; otherwise the loss counts as a transient
        failure (backoff, bounded by ``max_transient_retries``) so a deterministic bug cannot spin.
        Returns the new state, or None when the task was not RUNNING anymore.
        """
        actor = Actor("system", "watchdog")
        now = self.clock.now()
        with transaction(self.conn):
            task = self.engine._row(task_id)
            if task["state"] != TaskState.RUNNING:
                return None
            if self.engine._unknown_actions(task_id):
                self.engine.transition_in_txn(
                    task, TaskState.BLOCKED, actor, why, blocked_reason="EXTERNAL_EFFECT_UNKNOWN"
                )
                return TaskState.BLOCKED
            c = self._counters_in_txn(task_id)
            fails = int(c["transient_failures"]) + 1
            next_at = None
            if fails > self.limits.max_transient_retries:
                target, reason = TaskState.BLOCKED, "RETRY_LIMIT"
            else:
                target, reason = TaskState.RETRYING, None
                next_at = to_utc_str(now + backoff_delay(fails, self.limits, self.rng))
            self.conn.execute(
                "UPDATE task_progress SET transient_failures = ?, next_attempt_at = ?, updated_at = ?"
                " WHERE task_id = ?",
                (fails, next_at, to_utc_str(now), task_id),
            )
            self.engine.transition_in_txn(task, target, actor, why, blocked_reason=reason)
            return target

    def promote_due_retries(self) -> list[str]:
        """RETRYING -> READY once the backoff has elapsed (policy and budget are re-checked at dispatch)."""
        now = self.clock.now()
        promoted: list[str] = []
        with transaction(self.conn):
            rows = self.conn.execute(
                "SELECT t.*, p.next_attempt_at FROM tasks t JOIN task_progress p ON p.task_id = t.id"
                " WHERE t.state = 'RETRYING'"
            ).fetchall()
            for r in rows:
                if r["next_attempt_at"] is None or parse_utc(r["next_attempt_at"]) <= now:
                    self.engine.transition_in_txn(
                        r, TaskState.READY, Actor("system", "scheduler"), "backoff elapsed"
                    )
                    promoted.append(r["id"])
        return promoted


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Per-provider breaker: opens after N consecutive failures, probes once after a cool-down."""

    def __init__(self, clock: Clock, failure_threshold: int = 5, cooldown: timedelta = timedelta(seconds=30)):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self.clock = clock
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at: datetime | None = None

    def allow(self) -> bool:
        if self.state == BreakerState.OPEN:
            assert self._opened_at is not None
            if self.clock.now() - self._opened_at >= self.cooldown:
                self.state = BreakerState.HALF_OPEN
                return True
            return False
        return True

    def success(self) -> None:
        self.state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = None

    def failure(self) -> None:
        self._failures += 1
        if self.state == BreakerState.HALF_OPEN or self._failures >= self.failure_threshold:
            self.state = BreakerState.OPEN
            self._opened_at = self.clock.now()

    def guard(self) -> None:
        if not self.allow():
            raise AtlasError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "circuit open for this provider",
                recommended_action="wait for the cool-down; do not switch provider without consent",
            )
