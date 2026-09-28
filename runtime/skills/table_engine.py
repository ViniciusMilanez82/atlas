"""Bounded, data-only row transformations. No eval, dynamic imports, user expressions or I/O.

Decimal inputs use a dot (e.g. "1234.50"), not an ambiguous locale-dependent money string.
Numeric outputs are fixed-scale strings. Field names select literal dictionary keys only.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from decimal import Context, Decimal, DecimalException, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any

from shared.canonical import canonical_bytes
from shared.contracts import ContractError, validate, validator

DEFINITION_LIMIT = 128_000
ROWS_LIMIT = 256_000
OUTPUT_LIMIT = 512_000
_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]{0,23})(?:\.[0-9]{1,8})?$")


class TableError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def fingerprint() -> str:
    """Any interpreter OR schema change invalidates earlier test/activation evidence."""
    schema = canonical_bytes(validator("table_skill").schema)
    return hashlib.sha256(Path(__file__).read_bytes() + b"\0" + schema).hexdigest()


def _bounded(value: Any, limit: int) -> bytes:
    try:
        data = canonical_bytes(value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise TableError("INVALID_DATA") from exc
    if len(data) > limit:
        raise TableError("SIZE_LIMIT")
    return data


def validate_definition(definition: dict[str, Any]) -> None:
    _bounded(definition, DEFINITION_LIMIT)
    try:
        validate("table_skill", definition)
    except ContractError as exc:
        raise TableError("INVALID_DEFINITION") from exc
    names = [c["name"] for c in definition["columns"]]
    if len(set(names)) != len(names):
        raise TableError("DUPLICATE_COLUMN")
    positive = [t for t in definition["tests"] if "expected" in t and t["rows"]]
    if len({canonical_bytes(t["rows"]) for t in positive}) < 2:
        raise TableError("TWO_DISTINCT_POSITIVE_CASES_REQUIRED")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not _NUMBER.fullmatch(str(value)):
        raise TableError("NOT_DECIMAL")
    return Decimal(str(value))


def execute(definition: dict[str, Any], rows: Any, *, cancelled: Callable[[], bool] = lambda: False) -> list[dict[str, Any]]:
    validate_definition(definition)
    _bounded(rows, ROWS_LIMIT)
    rows_schema = validator("table_skill").schema["$defs"]["rows"]
    if not validator("table_skill").evolve(schema=rows_schema).is_valid(rows):
        raise TableError("INVALID_ROWS")
    output: list[dict[str, Any]] = []
    output_size = 2
    # Independent of ambient Decimal precision/traps/rounding in the host process.
    with localcontext(Context(prec=80, rounding=ROUND_HALF_UP)):
        for row in rows:
            if cancelled():
                raise TableError("CANCELLED")
            result: dict[str, Any] = {}
            for column in definition["columns"]:
                op = column["op"]
                fields = column.get("fields", [column["field"]] if "field" in column else [])
                if any(f not in row for f in fields):
                    raise TableError("MISSING_FIELD")
                value: Any
                if op == "literal":
                    value = column["value"]
                elif op == "copy":
                    value = row[column["field"]]
                elif op in ("upper", "lower", "strip"):
                    value = row[column["field"]]
                    if not isinstance(value, str):
                        raise TableError("NOT_TEXT")
                    value = {"upper": str.upper, "lower": str.lower, "strip": str.strip}[op](value)
                    if len(value) > 1000:
                        raise TableError("SIZE_LIMIT")
                else:
                    left, right = (_decimal(row[f]) for f in fields)
                    if op == "divide" and right == 0:
                        raise TableError("DIVIDE_BY_ZERO")
                    try:
                        if op == "add":
                            number = left + right
                        elif op == "subtract":
                            number = left - right
                        elif op == "multiply":
                            number = left * right
                        else:
                            number = left / right
                        number = number.quantize(Decimal(1).scaleb(-column["scale"]))
                        if not number.is_finite() or abs(number) >= Decimal("1e24"):
                            raise TableError("NUMBER_LIMIT")
                        value = format(abs(number) if number == 0 else number, "f")
                    except DecimalException as exc:
                        raise TableError("NUMBER_LIMIT") from exc
                result[column["name"]] = value
            output_size += len(canonical_bytes(result)) + 1
            if output_size > OUTPUT_LIMIT:
                raise TableError("SIZE_LIMIT")
            output.append(result)
    return output


def check_examples(definition: dict[str, Any], *, cancelled: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    validate_definition(definition)
    cases = []
    for test in definition["tests"]:
        if cancelled():
            raise TableError("CANCELLED")
        try:
            actual: Any = execute(definition, test["rows"], cancelled=cancelled)
            passed = "expected" in test and canonical_bytes(actual) == canonical_bytes(test["expected"])
            actual_error = None
        except TableError as exc:
            if exc.code == "CANCELLED":
                raise
            actual, actual_error = None, exc.code
            passed = test.get("expected_error") == actual_error
        cases.append({"label": test["label"], "passed": passed, "rows": test["rows"],
                      "expected": test.get("expected"), "expected_error": test.get("expected_error"),
                      "actual": actual, "actual_error": actual_error})
    return {"passed": all(c["passed"] for c in cases), "cases": cases, "engine_hash": fingerprint()}
