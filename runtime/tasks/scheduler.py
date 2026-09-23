"""Scheduled jobs (spec 9.3, AT-010.6).

Jobs carry an IANA timezone, the next run instant (UTC), a missed-run policy and a dedup key.
Resuming does not replay every overdue occurrence: the default policy consolidates missed
occurrences into one task and asks for confirmation when the template has external effects.
Occurrences are recorded in ``job_runs`` with a primary key, so a second scheduler pass (or a
concurrent one) cannot create duplicate tasks.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

MISSED_POLICIES = ("CONSOLIDATE_AND_CONFIRM", "SKIP", "RUN_ONCE")
SCHEDULER = Actor("system", "scheduler")


@dataclass(frozen=True)
class RunReport:
    job_id: str
    occurrence_at: str
    task_id: str | None
    missed_count: int
    needs_confirmation: bool


def next_local_occurrence(after: datetime, local_time: str, tz: str) -> datetime:
    """Next instant strictly after ``after`` at wall-clock ``local_time`` in ``tz`` (DST-aware).

    Non-existent local times (spring-forward gap) are shifted forward by fold rules of zoneinfo;
    ambiguous ones (fall-back) use the first occurrence.
    """
    zone = ZoneInfo(tz)
    hh, mm = (int(x) for x in local_time.split(":"))
    local_after = after.astimezone(zone)
    candidate_date = local_after.date()
    for _ in range(3):
        naive = datetime.combine(candidate_date, time(hh, mm))
        cand = naive.replace(tzinfo=zone, fold=0)
        # Normalize gaps: round-trip through UTC gives the real instant.
        cand_utc = cand.astimezone(ZoneInfo("UTC"))
        if cand_utc > after:
            return cand_utc
        candidate_date += timedelta(days=1)
    raise AssertionError("unreachable")


class Scheduler:
    def __init__(self, engine: TaskEngine) -> None:
        self.engine = engine
        self.conn: sqlite3.Connection = engine.conn
        self.clock: Clock = engine.clock

    def create_job(
        self,
        *,
        actor: Actor,
        employee_id: str,
        objective: str,
        timezone: str,
        dedup_key: str,
        local_time: str | None = None,
        interval_minutes: int | None = None,
        external_writes: bool = False,
        missed_policy: str = "CONSOLIDATE_AND_CONFIRM",
    ) -> str:
        if actor.kind != "owner":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner schedules recurring work")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"unknown IANA timezone {timezone!r}") from exc
        if (local_time is None) == (interval_minutes is None):
            raise AtlasError(ErrorCode.INVALID_INPUT, "choose exactly one of local_time or interval_minutes")
        if missed_policy not in MISSED_POLICIES:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown missed-run policy")
        now = self.clock.now()
        if local_time is not None:
            first = next_local_occurrence(now, local_time, timezone)
            interval = 1440
        else:
            assert interval_minutes is not None
            if interval_minutes < 1:
                raise AtlasError(ErrorCode.INVALID_INPUT, "interval must be at least one minute")
            first = now + timedelta(minutes=interval_minutes)
            interval = interval_minutes
        job_id = new_id()
        template = {"objective": objective, "external_writes": external_writes}
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO scheduled_jobs(id, employee_id, owner_id, template_json, timezone, interval_minutes,"
                " local_time, next_run_at, missed_policy, dedup_key, enabled) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                (
                    job_id,
                    employee_id,
                    actor.id,
                    json.dumps(template, sort_keys=True),
                    timezone,
                    interval,
                    local_time,
                    to_utc_str(first),
                    missed_policy,
                    dedup_key,
                ),
            )
        return job_id

    def _advance(self, job: sqlite3.Row, occurrence: datetime) -> datetime:
        if job["local_time"]:
            return next_local_occurrence(occurrence, job["local_time"], job["timezone"])
        return occurrence + timedelta(minutes=int(job["interval_minutes"]))

    def run_due(self) -> list[RunReport]:
        now = self.clock.now()
        reports: list[RunReport] = []
        with transaction(self.conn):
            jobs = self.conn.execute(
                "SELECT * FROM scheduled_jobs WHERE enabled = 1 ORDER BY next_run_at"
            ).fetchall()
            for job in jobs:
                due = parse_utc(job["next_run_at"])
                if due > now:
                    continue
                occurrences: list[datetime] = []
                cursor = due
                while cursor <= now and len(occurrences) < 10_000:
                    occurrences.append(cursor)
                    cursor = self._advance(job, cursor)
                latest = occurrences[-1]
                missed = len(occurrences) - 1
                template: dict[str, Any] = json.loads(job["template_json"])
                policy = job["missed_policy"]
                create = policy != "SKIP" or missed == 0
                needs_confirmation = (
                    policy == "CONSOLIDATE_AND_CONFIRM" and missed > 0 and bool(template["external_writes"])
                )
                occ_str = to_utc_str(latest)
                exists = self.conn.execute(
                    "SELECT 1 FROM job_runs WHERE job_id = ? AND occurrence_at = ?", (job["id"], occ_str)
                ).fetchone()
                task_id: str | None = None
                if create and not exists:
                    task_id = self._create_task_in_txn(job, template, missed, needs_confirmation)
                if not exists:
                    self.conn.execute(
                        "INSERT INTO job_runs(job_id, occurrence_at, task_id, missed_count, created_at)"
                        " VALUES (?,?,?,?,?)",
                        (job["id"], occ_str, task_id, missed, to_utc_str(now)),
                    )
                self.conn.execute(
                    "UPDATE scheduled_jobs SET next_run_at = ?, last_run_at = ? WHERE id = ?",
                    (to_utc_str(cursor), occ_str, job["id"]),
                )
                reports.append(RunReport(job["id"], occ_str, task_id, missed, needs_confirmation))
        return reports

    def _create_task_in_txn(
        self, job: sqlite3.Row, template: dict[str, Any], missed: int, needs_confirmation: bool
    ) -> str:
        """Create the consolidated task inside the scheduler transaction."""
        task_id = new_id()
        now = to_utc_str(self.clock.now())
        objective = template["objective"]
        if missed:
            objective = f"{objective} (consolidates {missed + 1} occurrences, {missed} missed)"
        self.conn.execute(
            "INSERT INTO tasks(id, owner_id, employee_id, objective, constraints_json, priority, data_policy,"
            " state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                job["owner_id"],
                job["employee_id"],
                objective[:4000],
                json.dumps({"external_writes": bool(template["external_writes"]), "purchases": False}),
                "NORMAL",
                "INTERNAL",
                TaskState.CREATED,
                now,
                now,
            ),
        )
        journal.append(
            self.conn,
            self.clock,
            employee_id=job["employee_id"],
            task_id=task_id,
            type="task.created",
            actor=SCHEDULER,
            summary=f"scheduled job {job['dedup_key']} ({missed} missed occurrence(s))",
        )
        if needs_confirmation:
            row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            self.engine.transition_in_txn(row, TaskState.UNDERSTANDING, SCHEDULER, "scheduled")
            row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            self.engine.transition_in_txn(
                row,
                TaskState.WAITING_USER,
                SCHEDULER,
                "missed occurrences with external effects were consolidated; owner confirmation required",
            )
        return task_id
