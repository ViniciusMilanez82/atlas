"""Lease keeper: renews a worker lease while the worker is blocked (A3-05, spec 6.4).

The worker thread blocks on model calls and tool dispatches that may legitimately outlast the lease
TTL. Renewal therefore runs on its own thread with its own SQLite connection, so it never waits for
the blocking call to return. It stops renewing when the lease was revoked (pause, stop, cancel,
reclaim: the fencing token no longer matches) or when the total run deadline is reached; after that
the lease expires and the watchdog reclaims the task. Increasing the TTL is not the fix.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import timedelta
from types import TracebackType

from runtime.tasks.engine import Lease, TaskEngine
from shared.clock import Clock
from shared.errors import AtlasError
from storage.db import StorageError, connect

DEFAULT_INTERVAL_S = 15.0
DEFAULT_MAX_TOTAL = timedelta(hours=2)


def database_path(conn: sqlite3.Connection) -> str | None:
    """File behind ``conn`` (None for in-memory databases, which cannot be shared across connections)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    return str(path) if path else None


class LeaseKeeper:
    def __init__(
        self,
        db_path: str,
        clock: Clock,
        lease: Lease,
        *,
        lease_ttl: timedelta,
        interval_s: float = DEFAULT_INTERVAL_S,
        max_total: timedelta = DEFAULT_MAX_TOTAL,
    ) -> None:
        if interval_s <= 0 or timedelta(seconds=interval_s) >= lease_ttl:
            raise ValueError("the heartbeat interval must be positive and shorter than the lease TTL")
        self.db_path = db_path
        self.clock = clock
        self.lease = lease
        self.lease_ttl = lease_ttl
        self.interval_s = interval_s
        self.deadline = clock.now() + max_total
        self.beats = 0
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"lease-keeper-{lease.task_id}", daemon=True)

    def __enter__(self) -> LeaseKeeper:
        self._thread.start()
        return self

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_s * 2))

    def _run(self) -> None:
        try:
            conn = connect(self.db_path)
        except (sqlite3.Error, StorageError):
            self.lost.set()
            return
        engine = TaskEngine(conn, self.clock, lease_ttl=self.lease_ttl)
        try:
            while not self._stop.wait(self.interval_s):
                if self.clock.now() >= self.deadline:
                    self.lost.set()  # total budget for one run exhausted: let the lease expire
                    return
                try:
                    self.lease = engine.heartbeat(self.lease)
                    self.beats += 1
                except AtlasError:
                    self.lost.set()  # revoked or reclaimed: never try to take it back
                    return
                except (sqlite3.Error, StorageError):
                    continue  # transient lock contention; the next beat retries well before expiry
        finally:
            conn.close()
