"""Deterministic calculation and time tools (N09, spec 8.3, 10, 13.3; scenario T06).

Numbers and dates are computed by code, never by the model:
* ``calc.evaluate``: arithmetic with Decimal (+ - * / ** parentheses, percent), Brazilian or dot-decimal
  notation, through a whitelisted AST (no names, calls or attributes: nothing can be executed).
* ``calendar.analyze``: expands events (instants in UTC, civil times in an IANA zone, all-day dates,
  daily/weekly recurrences with exceptions) inside a window and computes their overlaps. Daylight-saving
  transitions come from zoneinfo; an all-day event is the local civil day, not 24 UTC hours.

The same engine serves any set of authorized events: no calendar domain is hard-coded.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

getcontext().prec = 34
MAX_OCCURRENCES = 2_000


class ComputeError(ValueError):
    pass


# ---------------------------------------------------------------- arithmetic


def _normalize_number(tok: str, decimal_comma: bool) -> str:
    if decimal_comma:
        return tok.replace(".", "").replace(",", ".")
    return tok.replace(",", "")


def evaluate(expression: str, *, decimal_comma: bool = True) -> Decimal:
    if len(expression) > 500:
        raise ComputeError("expressão longa demais")
    number = r"\d+(?:[.,]\d+)*"
    expr = re.sub(r"(" + number + r")\s*%", r"(\1/100)", expression)
    expr = re.sub(number, lambda m: _normalize_number(m.group(0), decimal_comma), expr)
    expr = expr.replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise ComputeError("expressão inválida") from None

    def ev(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = ev(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            try:
                if isinstance(node.op, ast.Add):
                    return a + b
                if isinstance(node.op, ast.Sub):
                    return a - b
                if isinstance(node.op, ast.Mult):
                    return a * b
                if isinstance(node.op, ast.Div):
                    return a / b
                if isinstance(node.op, ast.Pow):
                    if abs(b) > 100 or b != b.to_integral_value():
                        raise ComputeError("potência fora do limite (inteiro até 100)")
                    return a**b
            except (DivisionByZero, InvalidOperation):
                raise ComputeError("divisão por zero ou operação inválida") from None
        raise ComputeError(f"elemento não permitido na expressão: {type(node).__name__}")

    return ev(tree)


def format_br(value: Decimal, places: int = 2) -> str:
    q = value.quantize(Decimal(1).scaleb(-places))
    sign = "-" if q < 0 else ""
    whole, _, frac = f"{abs(q):f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{grouped},{frac}" if places else f"{sign}{grouped}"


# ---------------------------------------------------------------- calendar


@dataclass(frozen=True)
class Occurrence:
    event_id: str
    title: str
    start: datetime  # UTC
    end: datetime  # UTC
    all_day: bool
    local_date: str

    def as_dict(self, tz: ZoneInfo) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "start_utc": self.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": self.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "start_local": self.start.astimezone(tz).isoformat(timespec="minutes"),
            "end_local": self.end.astimezone(tz).isoformat(timespec="minutes"),
            "all_day": self.all_day,
        }


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ComputeError(
            f"fuso horário desconhecido: {name!r} (use um nome IANA, ex. America/Sao_Paulo)"
        ) from None


def _instant(value: str, tz: ZoneInfo) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ComputeError(f"data/hora inválida: {value!r}") from None
    return (dt if dt.tzinfo else dt.replace(tzinfo=tz)).astimezone(UTC)


def _expand(ev: dict[str, Any], w_start: datetime, w_end: datetime) -> list[Occurrence]:
    tz = _zone(str(ev.get("timezone") or "UTC"))
    all_day = bool(ev.get("all_day"))
    rec = ev.get("recurrence") or {}
    freq = rec.get("freq")
    step = {"DAILY": timedelta(days=1), "WEEKLY": timedelta(weeks=1), None: None}.get(freq, "bad")
    if step == "bad":
        raise ComputeError(f"recorrência não suportada: {freq!r} (use DAILY ou WEEKLY)")
    interval = int(rec.get("interval", 1))
    count = rec.get("count")
    until = rec.get("until")
    exceptions = {str(d) for d in ev.get("exceptions", [])}
    if all_day:
        first = date.fromisoformat(str(ev["date"]))
        days = int(ev.get("days", 1))
    else:
        start = datetime.fromisoformat(str(ev["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ev["end"]).replace("Z", "+00:00"))
        if start.tzinfo is None:  # a civil time in the event's zone (DST applied per occurrence)
            local_start, local_end = start, end
        else:
            local_start, local_end = (
                start.astimezone(tz).replace(tzinfo=None),
                end.astimezone(tz).replace(tzinfo=None),
            )
        if local_end <= local_start:
            raise ComputeError(f"evento {ev.get('id')}: fim deve ser depois do início")
    out: list[Occurrence] = []
    n = 0
    while True:
        k = n * interval
        if all_day:
            d = first + (step * k if step else timedelta(0))  # type: ignore[operator]
            s = datetime.combine(d, time(0), tz).astimezone(UTC)
            e = datetime.combine(d + timedelta(days=days), time(0), tz).astimezone(UTC)
            label = d.isoformat()
        else:
            ls = local_start + (step * k if step else timedelta(0))  # type: ignore[operator]
            le = local_end + (step * k if step else timedelta(0))  # type: ignore[operator]
            s, e = ls.replace(tzinfo=tz).astimezone(UTC), le.replace(tzinfo=tz).astimezone(UTC)
            label = ls.date().isoformat()
        if until and label > str(until):
            break
        if s >= w_end and step:
            break
        if label not in exceptions and e > w_start and s < w_end:
            out.append(Occurrence(str(ev.get("id")), str(ev.get("title", "")), s, e, all_day, label))
        n += 1
        if not step or (count is not None and n >= int(count)) or n > MAX_OCCURRENCES:
            break
    return out


def analyze_calendar(events: list[dict[str, Any]], window: dict[str, str]) -> dict[str, Any]:
    tz = _zone(window.get("timezone", "UTC"))
    w_start, w_end = _instant(window["start"], tz), _instant(window["end"], tz)
    if w_end <= w_start:
        raise ComputeError("a janela precisa terminar depois de começar")
    occ: list[Occurrence] = []
    for ev in events:
        occ += _expand(ev, w_start, w_end)
    occ.sort(key=lambda o: (o.start, o.event_id))
    overlaps = []
    for i, a in enumerate(occ):
        for b in occ[i + 1 :]:
            if b.start >= a.end:
                break
            if a.event_id == b.event_id:
                continue
            s, e = max(a.start, b.start), min(a.end, b.end)
            overlaps.append(
                {
                    "events": [a.event_id, b.event_id],
                    "titles": [a.title, b.title],
                    "start_local": s.astimezone(tz).isoformat(timespec="minutes"),
                    "end_local": e.astimezone(tz).isoformat(timespec="minutes"),
                    "minutes": int((e - s).total_seconds() // 60),
                }
            )
    return {
        "timezone": window.get("timezone", "UTC"),
        "occurrences": [o.as_dict(tz) for o in occ],
        "overlaps": overlaps,
        "method": "deterministic expansion (zoneinfo); nothing estimated by the model",
    }
