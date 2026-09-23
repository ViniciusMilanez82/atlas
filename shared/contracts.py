"""JSON Schema contract loading and validation (spec 13, AT-002).

Schemas in ``shared/schemas`` are the language-neutral source of truth. Python, Swift and
TypeScript consumers validate against the same files.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_BASE_URI = "https://atlas.local/schemas/"

KNOWN_SCHEMAS = (
    "common",
    "action_proposal",
    "tool_result",
    "approval",
    "journal_event",
    "task",
    "ipc_request",
    "ipc_response",
    "config",
)


class ContractError(ValueError):
    """Raised when a payload violates its contract. Carries every violation found."""

    def __init__(self, schema: str, errors: list[str]) -> None:
        self.schema = schema
        self.errors = errors
        super().__init__(f"{schema}: {len(errors)} violation(s): " + "; ".join(errors[:5]))


def _load(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / f"{name}.schema.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for name in KNOWN_SCHEMAS:
        schema = _load(name)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@cache
def validator(name: str) -> Draft202012Validator:
    if name not in KNOWN_SCHEMAS:
        raise KeyError(f"unknown schema: {name}")
    schema = _load(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


def errors_for(name: str, payload: Any) -> list[str]:
    """Return a sorted list of human-readable violations (empty when valid)."""
    found: list[ValidationError] = sorted(
        validator(name).iter_errors(payload), key=lambda e: list(e.absolute_path)
    )
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in found]


def validate(name: str, payload: Any) -> None:
    """Validate ``payload`` against schema ``name``; raise :class:`ContractError` if invalid."""
    errs = errors_for(name, payload)
    if errs:
        raise ContractError(name, errs)
