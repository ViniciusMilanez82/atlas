"""Watchdog and independent housekeeping (A3-05, spec 6.4; scenario T21).

Runs on its own thread with its own connection, never behind a long task:
* RUNNING tasks whose lease expired without a heartbeat are reclaimed (fencing bumped, uncertain
  effects block for reconciliation, otherwise bounded retry with backoff);
* RETRYING tasks whose backoff elapsed go back to READY;
* scheduled jobs that are due create their tasks (deduplicated per occurrence).

Missing executor, expired lease and lack of progress are different conditions: this module handles
the lease; progress limits stay with ``ProgressGuard`` in the worker; executor health with
``core.health.WorkerMonitor``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from runtime.notifications.outbox import OutboxDispatcher
from runtime.tasks.engine import TaskEngine
from runtime.tasks.limits import ProgressGuard
from runtime.tasks.scheduler import RunReport, Scheduler
from shared.actors import Actor
from shared.clock import Clock, parse_utc


@dataclass
class WatchdogReport:
    reclaimed: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    scheduled: list[RunReport] = field(default_factory=list)
    delivered: int = 0


class Watchdog:
    ACTOR = Actor("system", "watchdog")

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock
        self.engine = TaskEngine(conn, clock)
        self.guard = ProgressGuard(self.engine)
        self.scheduler = Scheduler(self.engine)

    def expired_leases(self) -> list[str]:
        now = self.clock.now()
        rows = self.conn.execute("SELECT id, lease_expires_at FROM tasks WHERE state = 'RUNNING'").fetchall()
        return [r[0] for r in rows if r[1] is None or parse_utc(r[1]) <= now]

    def sweep(self) -> WatchdogReport:
        report = WatchdogReport()
        for task_id in self.expired_leases():
            if self.guard.reclaim_after_worker_loss(task_id, "lease expired without heartbeat") is not None:
                report.reclaimed.append(task_id)
        report.retried = self.guard.promote_due_retries()
        report.scheduled = self.scheduler.run_due()
        report.delivered = OutboxDispatcher(self.conn, self.clock).deliver_pending()  # A3-27 retries
        return report
