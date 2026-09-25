"""N09 / T06: numbers and dates by code - DST, time zones, all-day days, recurrences with exceptions.

Expected values ("gabarito") are written by hand before running. The last test goes through the real tool
path (broker -> builtin adapter) with a scripted FAKE model.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from runtime.tools.compute import ComputeError, analyze_calendar, evaluate, format_br
from tests.conftest import World
from tests.integration.test_agent_loop import SPEC, build, decision


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("1.000 - 900", "100"),
        ("12.345,67 + 0,33", "12346.00"),
        ("10% * 200", "20"),
        ("2 ** 10", "1024"),
        ("(1.500,50 - 500,50) / 4", "250.0"),
    ],
)
def test_arithmetic_is_exact(expr: str, expected: str) -> None:
    assert evaluate(expr) == Decimal(expected)


@pytest.mark.parametrize("expr", ["__import__('os')", "a + 1", "1 / 0", "2 ** 1000", "open('x')"])
def test_nothing_but_arithmetic_is_accepted(expr: str) -> None:
    with pytest.raises(ComputeError):
        evaluate(expr)


def test_brazilian_formatting() -> None:
    assert format_br(Decimal("12345.678")) == "12.345,68"


def test_weekly_meeting_keeps_local_time_across_dst() -> None:
    out = analyze_calendar(
        [
            {
                "id": "m",
                "title": "Reunião",
                "start": "2026-03-02T09:00",
                "end": "2026-03-02T10:00",
                "timezone": "America/New_York",
                "recurrence": {"freq": "WEEKLY", "count": 3},
            }
        ],
        {"start": "2026-03-01T00:00", "end": "2026-03-31T00:00", "timezone": "America/New_York"},
    )
    utc = [o["start_utc"] for o in out["occurrences"]]
    assert utc == ["2026-03-02T14:00:00Z", "2026-03-09T13:00:00Z", "2026-03-16T13:00:00Z"]  # DST on 03-08
    assert all(
        o["start_local"].endswith("09:00-05:00") or o["start_local"].endswith("09:00-04:00")
        for o in out["occurrences"]
    )


def test_all_day_is_the_local_civil_day() -> None:
    out = analyze_calendar(
        [
            {
                "id": "f",
                "title": "Feriado",
                "all_day": True,
                "date": "2026-05-01",
                "timezone": "America/Sao_Paulo",
            }
        ],
        {"start": "2026-04-30T00:00", "end": "2026-05-03T00:00", "timezone": "America/Sao_Paulo"},
    )
    o = out["occurrences"][0]
    assert (o["start_utc"], o["end_utc"]) == ("2026-05-01T03:00:00Z", "2026-05-02T03:00:00Z")


def test_overlap_across_time_zones_and_recurrence_exception() -> None:
    events = [
        {
            "id": "lis",
            "title": "Chamada Lisboa",
            "start": "2026-06-10T14:00",
            "end": "2026-06-10T15:00",
            "timezone": "Europe/Lisbon",
        },  # WEST: 13:00-14:00 UTC
        {
            "id": "sp",
            "title": "Consulta",
            "start": "2026-06-10T10:30",
            "end": "2026-06-10T11:30",
            "timezone": "America/Sao_Paulo",
        },  # 13:30-14:30 UTC
        {
            "id": "aula",
            "title": "Aula",
            "start": "2026-06-03T10:00",
            "end": "2026-06-03T11:00",
            "timezone": "America/Sao_Paulo",
            "recurrence": {"freq": "WEEKLY", "count": 4},
            "exceptions": ["2026-06-10"],
        },  # the class that would clash is cancelled that week
    ]
    out = analyze_calendar(
        events, {"start": "2026-06-01T00:00", "end": "2026-07-01T00:00", "timezone": "America/Sao_Paulo"}
    )
    assert [o["events"] for o in out["overlaps"]] == [["lis", "sp"]]
    assert out["overlaps"][0]["minutes"] == 30
    assert [o["start_utc"][:10] for o in out["occurrences"] if o["event_id"] == "aula"] == [
        "2026-06-03",
        "2026-06-17",
        "2026-06-24",
    ]


def test_tools_run_through_the_broker(world: World, tmp_path: Path) -> None:
    def policy(turn: int, prompt: str) -> str:
        if turn == 1:
            return decision("tool", tool="calc.evaluate", inp={"expression": "1.000 - 900"})
        return decision("ask_owner", question="ok?")

    s = build(world, tmp_path, policy)
    s.runner.catalog = s.runner._catalog([*s.runner.tools, "calc.evaluate", "calendar.analyze"])
    tid = s.tasks.create(
        world.owner, employee_id=world.employee.id, objective="conta", criteria=[("x", True)]
    )
    s.runner.run(tid, SPEC)
    obs = world.conn.execute("SELECT content FROM step_observations WHERE task_id = ?", (tid,)).fetchone()[0]
    assert json.loads(obs)["result"] == "100"
    assert re.search(r'"result_br": "100,00"', obs)
