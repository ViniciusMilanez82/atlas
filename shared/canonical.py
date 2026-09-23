"""Canonical JSON serialization and hashing (spec 11.2, 13.6).

Approvals bind to the SHA-256 of the canonical form of the action parameters. Any material
change (recipient, amount, items, attachments, terms) changes the hash and invalidates the
approval.

Rules: object keys sorted, no insignificant whitespace, UTF-8, and **floats are rejected** –
money and quantities must be integers in minor units so that the hash is unambiguous across
languages.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class CanonicalizationError(ValueError):
    pass


def _check(value: Any, path: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise CanonicalizationError(f"float not allowed in canonical payload at {path or '<root>'}")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalizationError(f"non-string key at {path or '<root>'}")
            _check(v, f"{path}/{k}")
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check(v, f"{path}/{i}")
        return
    raise CanonicalizationError(f"unsupported type {type(value).__name__} at {path or '<root>'}")


def canonical_bytes(value: Any) -> bytes:
    _check(value, "")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
