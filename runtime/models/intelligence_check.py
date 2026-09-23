"""'Testar inteligência' (spec 7.3): verify credential, model access, minimal structured output and
reported usage with ONE small call under an explicit cost ceiling.

Steps: (1) free metadata check that the account sees the model id; (2) one call through the budgeted
client with a tiny prompt and a strict JSON schema; (3) validate the output; (4) return evidence with
model id, request id, usage and computed cost from the versioned price table. The evidence never
contains the prompt or the key. Catalog presence is not access: a model becomes ``validated`` only
from a passing report.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from runtime.models.openai_responses import DEFAULT_BASE_URL, OpenAIResponsesProvider
from runtime.models.pricing import SPEC_REFERENCE_TABLE, PriceTable
from runtime.models.router import BudgetedModelClient, CatalogEntry, Consent, ModelRouter, Requirements
from runtime.models.types import Message, ModelCapabilities, ModelRequest, Role
from security.budget.budget import BudgetLimits, BudgetManager
from security.vault.vault import SecretValue
from shared.clock import SystemClock, to_utc_str
from shared.errors import AtlasError
from storage.db import transaction
from storage.repositories.identity import create_employee, create_owner
from storage.store import open_store

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "word": {"type": "string"}},
    "required": ["ok", "word"],
    "additionalProperties": False,
}


@dataclass
class IntelligenceReport:
    provider: str
    model_id: str
    price_table: str
    price_table_verified: bool
    checked_at: str
    model_listed: bool | None = None
    call_succeeded: bool = False
    output_valid: bool = False
    request_id: str | None = None
    usage: dict[str, int] | None = None
    cost_minor: int | None = None
    currency: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.model_listed and self.call_succeeded and self.output_valid and self.usage)

    def to_json(self) -> str:
        data = asdict(self)
        data["passed"] = self.passed
        return json.dumps(data, indent=2, sort_keys=True)


def run_intelligence_check(
    *,
    key_provider: Callable[[], SecretValue],
    model_id: str,
    max_cost_minor: int,
    currency: str = "USD",
    base_url: str = DEFAULT_BASE_URL,
    prices: PriceTable = SPEC_REFERENCE_TABLE,
    workdir: Path | None = None,
) -> IntelligenceReport:
    if max_cost_minor <= 0:
        raise ValueError("an explicit positive cost ceiling is required")
    clock = SystemClock()
    report = IntelligenceReport("openai", model_id, prices.version, prices.verified, to_utc_str(clock.now()))
    try:
        prices.get("openai", model_id)
    except KeyError:
        report.errors.append("model has no entry in the price table; refusing a billable call")
        return report
    caps = ModelCapabilities(structured_output=True)
    provider = OpenAIResponsesProvider(key_provider, capabilities={model_id: caps}, base_url=base_url)
    try:
        report.model_listed = provider.check_model_access(model_id)
    except AtlasError as exc:
        report.errors.append(f"model check failed: {exc.code}")
        return report
    except Exception as exc:
        report.errors.append(f"model check failed: {type(exc).__name__}")
        return report
    if not report.model_listed:
        report.errors.append("the account does not list this model id")
        return report

    workdir = workdir or Path(tempfile.mkdtemp(prefix="atlas-intel-"))
    conn = open_store(workdir / "check.sqlite", clock)
    try:
        owner = create_owner(conn, clock, "intelligence-check")
        emp = create_employee(conn, clock, owner_id=owner, name="check")
        from shared.ids import new_id

        task_id = new_id()
        with transaction(conn):
            conn.execute(
                "INSERT INTO tasks(id, owner_id, employee_id, objective, constraints_json, priority, data_policy,"
                " state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    owner,
                    emp.id,
                    "Testar inteligência",
                    '{"external_writes":false,"purchases":false}',
                    "NORMAL",
                    "PUBLIC",
                    "RUNNING",
                    to_utc_str(clock.now()),
                    to_utc_str(clock.now()),
                ),
            )
        client = BudgetedModelClient(
            conn,
            clock,
            ModelRouter(
                [CatalogEntry("openai", model_id, "general", 1, caps, validated=True)], Consent({"openai"})
            ),
            {"openai": provider},
            prices,
            BudgetManager(conn, clock, BudgetLimits(currency, max_cost_minor, max_cost_minor)),
        )
        request = ModelRequest(
            model_id,
            (Message(Role.USER, 'Reply with JSON: {"ok": true, "word": "atlas"}.'),),
            max_output_tokens=64,
            json_schema=SCHEMA,
            timeout_s=60,
        )
        try:
            resp = client.call(
                task_id=task_id,
                req=Requirements(structured_output=True, data_classification="PUBLIC"),
                request=request,
            )
        except AtlasError as exc:
            report.errors.append(f"call failed: {exc.code}: {exc.message}")
            return report
        report.call_succeeded = True
        report.request_id = resp.request_id
        if resp.usage:
            report.usage = {
                "input_tokens": resp.usage.input_tokens,
                "cached_input_tokens": resp.usage.cached_input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }
        if resp.estimated_cost:
            report.cost_minor = resp.estimated_cost.amount_minor
            report.currency = resp.estimated_cost.currency
        try:
            parsed: Any = json.loads(resp.output_text)
            report.output_valid = parsed.get("ok") is True and isinstance(parsed.get("word"), str)
        except (json.JSONDecodeError, AttributeError):
            report.errors.append("output was not the requested JSON")
        return report
    finally:
        conn.close()
