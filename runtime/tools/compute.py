"""Deterministic arithmetic and calendar tools (N09 / T06).

Decimal literals never pass through binary floats. Arithmetic uses a private 34-digit,
ROUND_HALF_EVEN context; inputs/results have explicit size bounds, not silent infinities.
Calendar answers cover the requested window completely or fail explicitly. Recurrences
keep civil time in their IANA zone; ambiguous/nonexistent civil times require clarification.
Explicit offsets identify instants and are never silently replaced by a DST default.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PRECISION = 34
MAX_MAGNITUDE = 1000
MAX_OCCURRENCES = 2_000
MAX_OVERLAPS = 10_000
_NUMBER = re.compile(r"[0-9.,]+(?:[eE][+-]?[0-9]+)?")


class ComputeError(ValueError):
    pass


def _context(precision: int = PRECISION) -> Context:
    return Context(prec=precision, rounding=ROUND_HALF_EVEN, Emin=-MAX_MAGNITUDE,
                   Emax=MAX_MAGNITUDE, traps=[InvalidOperation, DivisionByZero, Overflow, Underflow])


def _bounded(value: Decimal) -> Decimal:
    if not value.is_finite() or (value and abs(value.adjusted()) > MAX_MAGNITUDE):
        raise ComputeError("número fora do limite de magnitude")
    return value


def _normalize_number(token: str, decimal_comma: bool) -> str:
    sep, group = (",", ".") if decimal_comma else (".", ",")
    # Require actual groups of three: do not guess whether 1.23 meant 123 or 1,23.
    mantissa = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(group)}[0-9]{{3}})+)(?:{re.escape(sep)}[0-9]+)?"
    if not re.fullmatch(rf"(?:{mantissa}|{re.escape(sep)}[0-9]+)(?:[eE][+-]?[0-9]+)?", token):
        raise ComputeError("separadores numéricos inválidos para a notação escolhida")
    normalized = token.replace(group, "").replace(sep, ".")
    value = _bounded(Decimal(normalized))
    if len(value.as_tuple().digits) > PRECISION:
        raise ComputeError(f"literal ultrapassa {PRECISION} algarismos significativos")
    # Leading decimal separators and zeros need Python-compatible syntax for AST parsing.
    return str(value)


def _expression(expression: str, decimal_comma: bool) -> str:
    parts: list[str] = []
    i = 0
    operators = {"×": "*", "÷": "/", "−": "-", "^": "**"}
    while i < len(expression):
        char = expression[i]
        if char.isspace():
            parts.append(" ")
            i += 1
        elif char in "0123456789.,":
            match = _NUMBER.match(expression, i)
            assert match is not None
            number = _normalize_number(match.group(), decimal_comma)
            i = match.end()
            end = i
            while end < len(expression) and expression[end].isspace():
                end += 1
            if end < len(expression) and expression[end] == "%":
                number = f"({number}/100)"
                i = end + 1
            parts.append(number)
        elif char in "+-*/()^×÷−":
            parts.append(operators.get(char, char))
            i += 1
        else:
            raise ComputeError("elemento não permitido na expressão")
    return "".join(parts).strip()


def evaluate(expression: str, *, decimal_comma: bool = True) -> Decimal:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 500:
        raise ComputeError("expressão vazia ou longa demais (máximo de 500 caracteres)")
    try:
        with localcontext(_context()):
            expr = _expression(expression, decimal_comma)
            tree = ast.parse(expr, mode="eval")

            def ev(node: ast.AST, depth: int = 0) -> Decimal:
                if depth > 64:
                    raise ComputeError("expressão aninhada demais")
                if isinstance(node, ast.Expression):
                    return ev(node.body, depth + 1)
                if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                    # ast.Constant.value may already be rounded or inf: use the original token.
                    literal = ast.get_source_segment(expr, node)
                    if literal is None:
                        raise ComputeError("literal numérico indisponível")
                    return _bounded(Decimal(literal))
                if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                    value = ev(node.operand, depth + 1)
                    return value if isinstance(node.op, ast.UAdd) else -value
                if isinstance(node, ast.BinOp):
                    a, b = ev(node.left, depth + 1), ev(node.right, depth + 1)
                    if isinstance(node.op, ast.Add):
                        result = a + b
                    elif isinstance(node.op, ast.Sub):
                        result = a - b
                    elif isinstance(node.op, ast.Mult):
                        result = a * b
                    elif isinstance(node.op, ast.Div):
                        result = a / b
                    elif isinstance(node.op, ast.Pow):
                        if abs(b) > 100 or b != b.to_integral_value():
                            raise ComputeError("potência fora do limite (inteiro até 100)")
                        result = a**b
                    else:
                        raise ComputeError("operador não permitido")
                    return _bounded(result)
                raise ComputeError(f"elemento não permitido: {type(node).__name__}")

            return ev(tree)
    except (DecimalException, SyntaxError, RecursionError, OverflowError):
        raise ComputeError("operação inválida, divisão por zero ou limite numérico excedido") from None


def format_br(value: Decimal, places: int = 2) -> str:
    _bounded(value)
    if type(places) is not int or not 0 <= places <= PRECISION:
        raise ComputeError(f"casas decimais devem estar entre 0 e {PRECISION}")
    precision = max(PRECISION, len(value.as_tuple().digits), value.adjusted() + places + 2)
    try:
        with localcontext(_context(precision)):
            q = _bounded(value.quantize(Decimal(1).scaleb(-places)))
            sign = "-" if q < 0 else ""
            whole, _, frac = f"{abs(q):f}".partition(".")
            grouped = f"{int(whole):,}".replace(",", ".")
            return f"{sign}{grouped},{frac}" if places else f"{sign}{grouped}"
    except (DecimalException, ValueError):
        raise ComputeError("valor não pode ser formatado dentro dos limites") from None


@dataclass(frozen=True)
class Occurrence:
    event_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    local_date: str

    def as_dict(self, tz: ZoneInfo) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "title": self.title,
            "start_utc": self.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": self.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "start_local": self.start.astimezone(tz).isoformat(timespec="minutes"),
            "end_local": self.end.astimezone(tz).isoformat(timespec="minutes"),
            "all_day": self.all_day,
        }


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ComputeError(f"fuso horário desconhecido: {name!r}; use um nome IANA") from None


def _civil(dt: datetime, tz: ZoneInfo) -> datetime:
    """Round-trip both folds: reject gaps and unresolved folds instead of inventing an instant."""
    candidates = set()
    for fold in (0, 1):
        utc = dt.replace(tzinfo=tz, fold=fold).astimezone(UTC)
        if utc.astimezone(tz).replace(tzinfo=None) == dt:
            candidates.add(utc)
    if not candidates:
        raise ComputeError(f"horário local inexistente: {dt.isoformat()} em {tz.key}; corrija o horário")
    if len(candidates) != 1:
        raise ComputeError(f"horário local ambíguo: {dt.isoformat()} em {tz.key}; informe o deslocamento UTC")
    return candidates.pop()


def _instant(value: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(UTC) if dt.tzinfo is not None else _civil(dt, tz)


def _positive(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ComputeError(f"{name} deve ser inteiro entre 1 e {maximum}")
    return value


def _expand(ev: dict[str, Any], w_start: datetime, w_end: datetime) -> list[Occurrence]:
    tz = _zone(ev.get("timezone") or "UTC")
    all_day = ev.get("all_day", False)
    if type(all_day) is not bool:
        raise ComputeError("all_day deve ser booleano")
    rec = ev.get("recurrence", {})
    if not isinstance(rec, dict) or set(rec) - {"freq", "interval", "count", "until"}:
        raise ComputeError("recorrência inválida")
    freq = rec.get("freq")
    if freq not in (None, "DAILY", "WEEKLY") or (rec and freq is None):
        raise ComputeError("recorrência não suportada; use DAILY ou WEEKLY")
    interval = _positive(rec.get("interval", 1), "interval", 52)
    count = _positive(rec["count"], "count", 1000) if "count" in rec else None
    until = date.fromisoformat(rec["until"]) if "until" in rec else None
    raw_exceptions = ev.get("exceptions", [])
    if not isinstance(raw_exceptions, list) or len(raw_exceptions) > 200:
        raise ComputeError("exceptions deve conter no máximo 200 datas")
    exceptions = {date.fromisoformat(d) for d in raw_exceptions}
    if all_day:
        first = date.fromisoformat(ev["date"])
        days = _positive(ev.get("days", 1), "days", 366)
        local_start = datetime.combine(first, time.min)
        local_end = local_start + timedelta(days=days)
        original_start, original_end = _civil(local_start, tz), _civil(local_end, tz)
    else:
        original_start, original_end = _instant(ev["start"], tz), _instant(ev["end"], tz)
        local_start = original_start.astimezone(tz).replace(tzinfo=None)
        local_end = original_end.astimezone(tz).replace(tzinfo=None)
    if original_end <= original_start:
        raise ComputeError(f"evento {ev.get('id')}: fim deve ser depois do início")
    if freq and local_end <= local_start:
        raise ComputeError("recorrência atravessa horário repetido; esclareça a duração civil")
    step_days = (1 if freq == "DAILY" else 7) * interval if freq else 0
    # Seek near the window, retaining ordinal/count semantics and long overlapping events.
    # Two extra periods conservatively cover civil/UTC offset changes near the boundary.
    elapsed = (w_start.astimezone(tz).replace(tzinfo=None) - local_end).days
    n = max(0, elapsed // step_days - 2) if step_days else 0
    last_date = w_end.astimezone(tz).date()
    out: list[Occurrence] = []
    while count is None or n < count:
        shifted_ordinal = local_start.date().toordinal() + step_days * n
        if shifted_ordinal > last_date.toordinal():
            break
        delta = timedelta(days=step_days * n)
        ls, le = local_start + delta, local_end + delta
        if until is not None and ls.date() > until:
            break
        if ls.date() not in exceptions:
            # n=0 preserves an explicitly offset-aware original, including fold=1.
            s, e = (original_start, original_end) if n == 0 else (_civil(ls, tz), _civil(le, tz))
            if e <= s:
                raise ComputeError("ocorrência tem duração inválida")
            if e > w_start and s < w_end:
                out.append(Occurrence(ev["id"], str(ev.get("title", "")), s, e, all_day, ls.date().isoformat()))
                if len(out) > MAX_OCCURRENCES:
                    raise ComputeError("janela excede o limite de ocorrências; reduza o período consultado")
        if not step_days:
            break
        n += 1
    return out


def analyze_calendar(events: list[dict[str, Any]], window: dict[str, str]) -> dict[str, Any]:
    try:
        if not isinstance(events, list) or len(events) > 200:
            raise ComputeError("consulta limitada a 200 eventos")
        ids = [ev["id"] for ev in events]
        if any(not isinstance(i, str) or not i or len(i) > 100 for i in ids) or len(set(ids)) != len(ids):
            raise ComputeError("cada evento deve ter um id único e não vazio")
        tz = _zone(window.get("timezone", "UTC"))
        w_start, w_end = _instant(window["start"], tz), _instant(window["end"], tz)
        if w_end <= w_start:
            raise ComputeError("a janela precisa terminar depois de começar")
        occ: list[Occurrence] = []
        for ev in events:
            occ.extend(_expand(ev, w_start, w_end))
            if len(occ) > MAX_OCCURRENCES:
                raise ComputeError("consulta excede o limite total de ocorrências; reduza o período")
        occ.sort(key=lambda o: (o.start, o.event_id))
        overlaps = []
        for i, a in enumerate(occ):
            for b in occ[i + 1:]:
                if b.start >= a.end:
                    break
                if a.event_id == b.event_id:
                    continue
                s, e = max(a.start, b.start, w_start), min(a.end, b.end, w_end)
                if e <= s:
                    continue
                overlaps.append({
                    "events": [a.event_id, b.event_id], "titles": [a.title, b.title],
                    "start_local": s.astimezone(tz).isoformat(timespec="minutes"),
                    "end_local": e.astimezone(tz).isoformat(timespec="minutes"),
                    "minutes": int((e - s).total_seconds() // 60),
                })
                if len(overlaps) > MAX_OVERLAPS:
                    raise ComputeError("consulta excede o limite de conflitos; reduza o período ou os eventos")
        return {"timezone": window.get("timezone", "UTC"),
                "occurrences": [o.as_dict(tz) for o in occ], "overlaps": overlaps,
                "method": "deterministic bounded expansion (zoneinfo); ambiguous civil times are refused"}
    except ComputeError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        raise ComputeError("dados de calendário inválidos ou fora do intervalo suportado") from None
