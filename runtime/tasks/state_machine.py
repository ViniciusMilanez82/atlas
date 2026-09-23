"""Task state machine (spec 9.2).

Normal flow: CREATED -> UNDERSTANDING -> PLANNING -> READY -> RUNNING -> VERIFYING -> COMPLETED.
VERIFYING may return to PLANNING for a viable repair. Wait states return to READY only when their
condition is resolved and policy/budget are re-evaluated (enforced by the engine, not here).
"""

from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    CREATED = "CREATED"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    BLOCKED = "BLOCKED"
    RETRYING = "RETRYING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


S = TaskState
TERMINAL = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED})
WAIT_STATES = frozenset({S.WAITING_USER, S.WAITING_APPROVAL, S.BLOCKED, S.RETRYING})
_ANY_ACTIVE = frozenset(S) - TERMINAL

ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    S.CREATED: frozenset({S.UNDERSTANDING, S.PAUSED, S.CANCELLED}),
    S.UNDERSTANDING: frozenset({S.PLANNING, S.WAITING_USER, S.FAILED, S.PAUSED, S.CANCELLED}),
    S.PLANNING: frozenset({S.READY, S.WAITING_USER, S.FAILED, S.PAUSED, S.CANCELLED}),
    S.READY: frozenset({S.RUNNING, S.PLANNING, S.BLOCKED, S.PAUSED, S.CANCELLED}),
    S.RUNNING: frozenset(
        {
            S.READY,
            S.VERIFYING,
            S.WAITING_USER,
            S.WAITING_APPROVAL,
            S.BLOCKED,
            S.RETRYING,
            S.PAUSED,
            S.FAILED,
            S.CANCELLED,
        }
    ),
    S.WAITING_USER: frozenset({S.READY, S.UNDERSTANDING, S.PLANNING, S.PAUSED, S.CANCELLED, S.FAILED}),
    S.WAITING_APPROVAL: frozenset({S.READY, S.PAUSED, S.CANCELLED, S.FAILED}),
    S.BLOCKED: frozenset({S.READY, S.PAUSED, S.CANCELLED, S.FAILED}),
    S.RETRYING: frozenset({S.READY, S.PAUSED, S.CANCELLED, S.FAILED}),
    # Resume re-evaluates and may land back in a wait state (engine decides which).
    S.PAUSED: frozenset(
        {
            S.CREATED,
            S.UNDERSTANDING,
            S.PLANNING,
            S.READY,
            S.WAITING_USER,
            S.WAITING_APPROVAL,
            S.BLOCKED,
            S.VERIFYING,
            S.CANCELLED,
        }
    ),
    S.VERIFYING: frozenset({S.COMPLETED, S.PLANNING, S.WAITING_USER, S.FAILED, S.PAUSED, S.CANCELLED}),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset(),
    S.CANCELLED: frozenset(),
}


class InvalidTransition(ValueError):
    def __init__(self, src: str, dst: str) -> None:
        super().__init__(f"invalid task transition {src} -> {dst}")
        self.src = src
        self.dst = dst


def check_transition(src: str, dst: str) -> None:
    try:
        s, d = TaskState(src), TaskState(dst)
    except ValueError as exc:
        raise InvalidTransition(src, dst) from exc
    if d not in ALLOWED[s]:
        raise InvalidTransition(src, dst)
