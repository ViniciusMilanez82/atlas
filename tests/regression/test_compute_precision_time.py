"""N09 / T06: exact literals and complete, unambiguous calendar answers.

Uses the production functions and builtin adapters, with synthetic data only.
No provider, network, Mac UI, or owner credentials are involved.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, getcontext, localcontext
from pathlib import Path

import pytest

from runtime.tools.builtin import BuiltinTools
from runtime.tools.compute import ComputeError, analyze_calendar, evaluate, format_br
from shared.clock import ManualClock


@pytest.mark.parametrize(("expression", "comma", "expected"), [
    ("1234567890123456,78 - 1234567890123456,77", True, "0.01"),
    ("1234567890123456.78 - 1234567890123456.77", False, "0.01"),
    ("0,1234567890123456789012345678901234", True, "0.1234567890123456789012345678901234"),
    ("1e-400", False, "1e-400"),
    ("1,25e2% * 80", True, "100"),
    ("12.345,67 + 0,33", True, "12346"),
    ("12,345.67 + 0.33", False, "12346"),
    ("(1.500,50 - 500,50) / 4", True, "250"),
    ("2 ^ 10", True, "1024"),
    ("10% * 200", True, "20"),
])
def test_decimal_literals_never_round_trip_through_float(expression, comma, expected):
    assert evaluate(expression, decimal_comma=comma) == Decimal(expected)


def test_decimal_context_is_private_and_deterministic():
    with localcontext() as caller:
        caller.prec = 6
        caller.rounding = ROUND_DOWN
        before = caller.copy()
        assert evaluate("123456789,01 + 0,01") == Decimal("123456789.02")
        assert format_br(Decimal("12345.678")) == "12.345,68"
        assert getcontext().prec == before.prec
        assert getcontext().rounding == before.rounding
        assert getcontext().flags == before.flags


@pytest.mark.parametrize("expression", [
    "1e1001", "1e-1001", "(10 ** 100) ** 100", "1 / 0", "2 ** 101",
    "True", "__import__('os')", "1_000", "0x10", "1 // 2", "1.23 + 4",
])
def test_invalid_or_unbounded_calculations_are_controlled_errors(expression):
    with pytest.raises(ComputeError):
        evaluate(expression)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_formatting_rejects_nonfinite_values(value):
    with pytest.raises(ComputeError):
        format_br(value)


def _window(start="2026-09-25T00:00", end="2026-09-26T00:00", zone="America/Sao_Paulo"):
    return {"start": start, "end": end, "timezone": zone}


def _daily(**changes):
    return {"id": "daily", "start": "2010-01-01T09:00", "end": "2010-01-01T10:00",
            "timezone": "America/Sao_Paulo", "recurrence": {"freq": "DAILY"}, **changes}


def test_old_unbounded_recurrence_is_found_without_scanning_its_lifetime():
    out = analyze_calendar([_daily()], _window())
    assert [o["start_utc"] for o in out["occurrences"]] == ["2026-09-25T12:00:00Z"]


def test_occurrence_count_and_exceptions_are_not_reset_by_window_seek():
    assert not analyze_calendar([_daily(recurrence={"freq": "DAILY", "count": 10})], _window())["occurrences"]
    assert not analyze_calendar([_daily(exceptions=["2026-09-25"])], _window())["occurrences"]
    assert not analyze_calendar([_daily(recurrence={"freq": "DAILY", "until": "2026-09-24"})], _window())["occurrences"]


def test_large_window_is_explicitly_refused_instead_of_silently_truncated():
    with pytest.raises(ComputeError):
        analyze_calendar([_daily()], _window("2010-01-01T00:00", "2026-09-26T00:00"))


def test_explicit_offset_during_repeated_hour_is_preserved():
    ev = {"id": "offset", "start": "2026-11-01T01:15:00-05:00", "end": "2026-11-01T01:45:00-05:00",
          "timezone": "America/New_York"}
    out = analyze_calendar([ev], _window("2026-11-01T00:00", "2026-11-02T00:00", "America/New_York"))
    assert out["occurrences"][0]["start_utc"] == "2026-11-01T06:15:00Z"


def test_positive_interval_across_repeated_hour_is_not_compared_as_wall_clock():
    ev = {"id": "cross", "start": "2026-11-01T01:45:00-04:00", "end": "2026-11-01T01:15:00-05:00",
          "timezone": "America/New_York"}
    out = analyze_calendar([ev], _window("2026-11-01T00:00", "2026-11-02T00:00", "America/New_York"))
    assert out["occurrences"][0]["end_utc"] == "2026-11-01T06:15:00Z"


@pytest.mark.parametrize(("start", "end"), [
    ("2026-03-08T02:15", "2026-03-08T02:45"),
    ("2026-11-01T01:15", "2026-11-01T01:45"),
])
def test_missing_or_ambiguous_civil_time_needs_an_explicit_decision(start, end):
    ev = {"id": "civil", "start": start, "end": end, "timezone": "America/New_York"}
    with pytest.raises(ComputeError):
        analyze_calendar([ev], _window(start[:10] + "T00:00", start[:10] + "T23:59", "America/New_York"))


@pytest.mark.parametrize(("day", "hours"), [("2026-03-08", 23), ("2026-11-01", 25)])
def test_all_day_has_real_civil_day_duration(day, hours):
    from datetime import datetime
    ev = {"id": "day", "all_day": True, "date": day, "timezone": "America/New_York"}
    out = analyze_calendar([ev], _window(day + "T00:00", day + "T23:59", "America/New_York"))
    o = out["occurrences"][0]
    assert (datetime.fromisoformat(o["end_utc"]) - datetime.fromisoformat(o["start_utc"])).total_seconds() == hours * 3600


def test_weekly_local_time_is_preserved_across_dst():
    ev = {"id": "meeting", "start": "2026-03-02T09:00", "end": "2026-03-02T10:00",
          "timezone": "America/New_York", "recurrence": {"freq": "WEEKLY", "count": 3}}
    out = analyze_calendar([ev], _window("2026-03-01T00:00", "2026-03-31T00:00", "America/New_York"))
    assert [o["start_utc"] for o in out["occurrences"]] == [
        "2026-03-02T14:00:00Z", "2026-03-09T13:00:00Z", "2026-03-16T13:00:00Z"]


@pytest.mark.parametrize("recurrence", [
    {"freq": "DAILY", "interval": 0}, {"freq": "DAILY", "interval": -1},
    {"freq": "DAILY", "interval": True}, {"freq": "DAILY", "count": 0},
    {"freq": "DAILY", "count": 1.5}, {"freq": "DAILY", "until": "not-a-date"},
])
def test_invalid_recurrence_is_not_reported_as_a_success(recurrence):
    with pytest.raises(ComputeError):
        analyze_calendar([_daily(start="2026-09-25T09:00", end="2026-09-25T10:00", recurrence=recurrence)], _window())


def test_duplicate_event_ids_are_rejected_not_hidden_as_non_overlapping():
    with pytest.raises(ComputeError):
        analyze_calendar([_daily(), _daily()], _window())


def test_overlap_is_clipped_to_the_requested_window():
    a = _daily(id="a", start="2026-09-25T09:00", end="2026-09-25T12:00", recurrence={})
    b = _daily(id="b", start="2026-09-25T09:30", end="2026-09-25T13:00", recurrence={})
    out = analyze_calendar([a, b], _window("2026-09-25T10:00", "2026-09-25T11:00"))
    assert out["overlaps"][0]["minutes"] == 60


def test_production_tool_adapters_report_correct_result_and_controlled_failure(tmp_path: Path):
    tools = BuiltinTools(tmp_path / "unused.sqlite", tmp_path / "artifacts", ManualClock())
    result = tools.calc({"expression": "1234567890123456,78 - 1234567890123456,77"}, None)
    assert result.status == "SUCCEEDED"
    assert result.output["result_br"] == "0,01"
    assert tools.calc({"expression": "1e1001"}, None).status == "FAILED"
    assert tools.calendar({"events": [_daily()], "window": _window()}, None).output["occurrences"]
