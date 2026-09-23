"""AT-010.1: state machine of spec 9.2."""

from __future__ import annotations

from itertools import pairwise

import pytest

from runtime.tasks.state_machine import ALLOWED, TERMINAL, InvalidTransition, TaskState, check_transition
from shared.contracts import validator

S = TaskState


def test_states_match_the_contract_enum() -> None:
    schema_enum = validator("common").schema["$defs"]["task_state"]["enum"]
    assert set(schema_enum) == {s.value for s in TaskState}


def test_normal_flow_is_allowed() -> None:
    flow = [S.CREATED, S.UNDERSTANDING, S.PLANNING, S.READY, S.RUNNING, S.VERIFYING, S.COMPLETED]
    for a, b in pairwise(flow):
        check_transition(a, b)


def test_verifying_can_return_to_planning_for_repair() -> None:
    check_transition(S.VERIFYING, S.PLANNING)


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
def test_terminal_states_are_final(terminal: TaskState) -> None:
    for dst in TaskState:
        with pytest.raises(InvalidTransition):
            check_transition(terminal, dst)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (S.CREATED, S.RUNNING),
        (S.CREATED, S.COMPLETED),
        (S.READY, S.COMPLETED),
        (S.RUNNING, S.COMPLETED),  # must pass through VERIFYING
        (S.WAITING_APPROVAL, S.RUNNING),  # must go back to READY for re-evaluation
        (S.BLOCKED, S.RUNNING),
        (S.PAUSED, S.RUNNING),
    ],
)
def test_shortcuts_are_rejected(src: TaskState, dst: TaskState) -> None:
    with pytest.raises(InvalidTransition):
        check_transition(src, dst)


def test_every_active_state_can_be_cancelled() -> None:
    for s in TaskState:
        if s not in TERMINAL:
            assert S.CANCELLED in ALLOWED[s], s


def test_wait_states_only_leave_through_ready_or_control() -> None:
    for s in (S.WAITING_APPROVAL, S.BLOCKED, S.RETRYING):
        assert ALLOWED[s] <= {S.READY, S.PAUSED, S.CANCELLED, S.FAILED}


def test_unknown_state_rejected() -> None:
    with pytest.raises(InvalidTransition):
        check_transition("RUNNING", "DONE")
