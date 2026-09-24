"""Executor health shared between the worker thread and the IPC handlers (A3-06, spec 6.5).

"Process alive" is not "executor healthy": the worker beats on every loop iteration, records the last
unexpected error and says when it stopped. ``system.health`` reads this snapshot, so a dead or stuck
worker is reported instead of a green status.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from shared.clock import Clock, to_utc_str


@dataclass
class WorkerMonitor:
    clock: Clock
    stale_after_s: float = 120.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _state: str = "not_started"  # not_started | starting | running | stopped
    _last_beat: datetime | None = None
    _last_error: str | None = None
    _last_error_at: datetime | None = None
    _errors: int = 0

    def starting(self) -> None:
        """The worker thread was launched but has not run its first iteration yet."""
        with self._lock:
            if self._state == "not_started":
                self._state = "starting"

    def started(self) -> None:
        with self._lock:
            self._state = "running"
            self._last_beat = self.clock.now()

    def beat(self) -> None:
        with self._lock:
            self._last_beat = self.clock.now()

    def error(self, description: str) -> None:
        with self._lock:
            self._errors += 1
            self._last_error = description[:300]
            self._last_error_at = self.clock.now()

    def stopped(self, description: str | None = None) -> None:
        with self._lock:
            self._state = "stopped"
            if description:
                self._last_error = description[:300]
                self._last_error_at = self.clock.now()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self.clock.now()
            if self._state == "running":
                assert self._last_beat is not None
                if (now - self._last_beat).total_seconds() > self.stale_after_s:
                    component = "stale"
                elif self._last_error_at is not None and self._last_error_at >= self._last_beat:
                    component = "degraded"
                else:
                    component = "ok"
            else:
                component = self._state
            return {
                "state": component,
                "last_beat": to_utc_str(self._last_beat) if self._last_beat else None,
                "last_error": self._last_error,
                "errors": self._errors,
            }
