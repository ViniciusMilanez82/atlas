"""Injectable clock. Instants are UTC; formatting always uses the ``Z`` suffix (spec 8.4, 13.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """Deterministic clock for tests and simulations."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        if self._now.tzinfo is None:
            raise ValueError("ManualClock requires an aware datetime")

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


def to_utc_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed; instants must be timezone-aware")
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError(f"not a UTC instant: {value!r}")
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)
