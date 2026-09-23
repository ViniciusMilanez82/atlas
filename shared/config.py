"""Declarative configuration loading (spec 7.5).

The YAML is validated against ``config.schema.json`` plus semantic rules that JSON Schema
cannot express. Null budget limits mean "pending setup": paid calls stay blocked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.contracts import ContractError, validate
from shared.money import CURRENCY_EXPONENT


def semantic_errors(cfg: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    intel = cfg["intelligence"]
    if intel["default_profile"] not in intel["profiles"]:
        errs.append(f"default_profile {intel['default_profile']!r} is not a defined profile")
    providers = {p["provider"] for p in intel["profiles"].values()}
    if len(providers) > 1 and intel["allow_cross_provider_fallback"]:
        # Allowed only with explicit owner consent recorded elsewhere; config alone cannot grant it.
        errs.append("cross-provider fallback cannot be enabled from configuration alone")
    budget = cfg["budget"]
    if budget["currency"] not in CURRENCY_EXPONENT:
        errs.append(f"unsupported budget currency {budget['currency']!r}")
    m, t = budget["monthly_limit_minor"], budget["per_task_limit_minor"]
    if m is not None and t is not None and t > m:
        errs.append("per_task_limit_minor exceeds monthly_limit_minor")
    if sorted(budget["warning_percentages"]) != budget["warning_percentages"]:
        errs.append("warning_percentages must be ascending")
    return errs


def parse_config(data: Any) -> dict[str, Any]:
    validate("config", data)
    errs = semantic_errors(data)
    if errs:
        raise ContractError("config", errs)
    result: dict[str, Any] = data
    return result


def load_config(path: Path) -> dict[str, Any]:
    return parse_config(yaml.safe_load(path.read_text(encoding="utf-8")))


def paid_calls_configured(cfg: dict[str, Any]) -> bool:
    """True only when the owner configured both a period and a per-task ceiling."""
    b = cfg["budget"]
    return b["monthly_limit_minor"] is not None and b["per_task_limit_minor"] is not None
