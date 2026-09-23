"""AT-002 contract tests.

Acceptance: valid fixtures pass; extra fields, invalid enums and money without currency fail.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from shared.contracts import KNOWN_SCHEMAS, SCHEMA_DIR, errors_for

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures" / "valid"


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("name", KNOWN_SCHEMAS)
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_every_schema_file_is_registered() -> None:
    on_disk = {p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json")}
    assert on_disk == set(KNOWN_SCHEMAS)


@pytest.mark.parametrize("name", [n for n in KNOWN_SCHEMAS if n != "common"])
def test_valid_fixture_passes(name: str) -> None:
    assert errors_for(name, fixture(name)) == []


# --- extra fields are forbidden -------------------------------------------------------------

EXTRA_FIELD_CASES = [
    ("task", []),
    ("action_proposal", []),
    ("action_proposal", ["verification"]),
    ("tool_result", []),
    ("tool_result", ["observability"]),
    ("approval", []),
    ("approval", ["purchase"]),
    ("journal_event", []),
    ("journal_event", ["actor"]),
    ("ipc_request", []),
    ("ipc_request", ["params"]),
    ("ipc_request", ["params", "constraints"]),
    ("config", []),
    ("config", ["security"]),
]


@pytest.mark.parametrize(("name", "path"), EXTRA_FIELD_CASES)
def test_extra_field_rejected(name: str, path: list[str]) -> None:
    data = fixture(name)
    target = data
    for key in path:
        target = target[key]
    target["unexpected_field"] = True
    assert errors_for(name, data), f"{name}{path} accepted an extra field"


# --- invalid enums --------------------------------------------------------------------------

INVALID_ENUM_CASES = [
    ("task", ["state"], "DONE"),
    ("task", ["priority"], "CRITICAL"),
    ("task", ["data_policy"], "TOP_SECRET"),
    ("tool_result", ["operation_status"], "OK"),
    ("tool_result", ["retry_class"], "ALWAYS"),
    ("approval", ["status"], "ACCEPTED"),
    ("approval", ["risk_class"], "R9"),
    ("journal_event", ["actor", "kind"], "llm"),
    ("ipc_request", ["method"], "shell.exec"),
    ("ipc_response", ["error", "data", "atlas_code"], "OOPS"),
    ("config", ["intelligence", "mode"], "yolo"),
    ("action_proposal", ["verification", "kind"], "model_says_ok"),
]


@pytest.mark.parametrize(("name", "path", "value"), INVALID_ENUM_CASES)
def test_invalid_enum_rejected(name: str, path: list[str], value: str) -> None:
    data = fixture(name)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert errors_for(name, data)


# --- money always needs a currency ----------------------------------------------------------


def test_money_without_currency_rejected_in_task() -> None:
    data = fixture("task")
    data["budget_limit"] = {"amount_minor": 500}
    assert errors_for("task", data)


def test_money_without_currency_rejected_in_approval() -> None:
    data = fixture("approval")
    del data["max_cost"]["currency"]
    assert errors_for("approval", data)


def test_money_as_float_rejected() -> None:
    data = fixture("approval")
    data["max_cost"]["amount_minor"] = 129.90
    assert errors_for("approval", data)


def test_money_lowercase_currency_rejected() -> None:
    data = fixture("task")
    data["budget_limit"]["currency"] = "usd"
    assert errors_for("task", data)


# --- security-relevant contract rules -------------------------------------------------------


@pytest.mark.parametrize("field", ["effect", "risk_class", "params_hash", "credential_ref", "approved"])
def test_llm_proposal_cannot_carry_authority_fields(field: str) -> None:
    data = fixture("action_proposal")
    data[field] = "READ_ONLY" if field == "effect" else "x"
    assert errors_for("action_proposal", data)


@pytest.mark.parametrize("field", ["actor", "actor_id"])
def test_ipc_params_cannot_declare_actor(field: str) -> None:
    data = fixture("ipc_request")
    data["params"][field] = "owner"
    assert errors_for("ipc_request", data)


def test_r5_approval_cannot_exist() -> None:
    data = fixture("approval")
    data["risk_class"] = "R5"
    assert errors_for("approval", data)


def test_purchase_approval_requires_purchase_details_and_cost() -> None:
    data = fixture("approval")
    del data["purchase"]
    assert errors_for("approval", data)
    data = fixture("approval")
    data["max_cost"] = None
    assert errors_for("approval", data)


def test_unknown_tool_result_cannot_claim_success() -> None:
    data = fixture("tool_result")
    data["success"] = True
    assert errors_for("tool_result", data)


def test_unknown_tool_result_cannot_be_transient_retry() -> None:
    data = fixture("tool_result")
    data["retry_class"] = "TRANSIENT"
    assert errors_for("tool_result", data)


def test_blocked_task_requires_reason_and_others_forbid_it() -> None:
    data = fixture("task")
    data["state"] = "BLOCKED"
    assert errors_for("task", data)
    data["blocked_reason"] = "EXTERNAL_EFFECT_UNKNOWN"
    assert errors_for("task", data) == []
    data["state"] = "RUNNING"
    assert errors_for("task", data)


def test_timestamps_must_be_utc() -> None:
    data = fixture("task")
    data["created_at"] = "2026-09-22T09:00:00-03:00"
    assert errors_for("task", data)


def test_ids_must_be_uuids_not_llm_labels() -> None:
    data = fixture("action_proposal")
    data["task_id"] = "task-example-001"
    assert errors_for("action_proposal", data)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["security", "host_shell_enabled"], True),
        (["security", "unreviewed_code_network_enabled"], True),
        (["security", "purchases_require_scoped_approval"], False),
        (["security", "raw_secrets_in_model_context"], True),
        (["budget", "require_owner_setup_before_paid_calls"], False),
        (["intelligence", "max_external_effect_workers"], 3),
        (["intelligence", "max_parallel_research_workers"], 10),
    ],
)
def test_config_cannot_widen_security(path: list[str], value: object) -> None:
    data = copy.deepcopy(fixture("config"))
    data[path[0]][path[1]] = value
    assert errors_for("config", data)


def test_ipc_response_needs_exactly_one_of_result_or_error() -> None:
    data = fixture("ipc_response")
    data["result"] = {}
    assert errors_for("ipc_response", data)
    del data["error"]
    assert errors_for("ipc_response", data) == []
    del data["result"]
    assert errors_for("ipc_response", data)


def test_every_mandatory_ipc_method_has_a_strict_params_schema() -> None:
    schema = json.loads((SCHEMA_DIR / "ipc_request.schema.json").read_text(encoding="utf-8"))
    methods = set(schema["properties"]["method"]["enum"])
    covered: set[str] = set()
    for clause in schema["allOf"]:
        cond = clause["if"]["properties"]["method"]
        covered |= {cond["const"]} if "const" in cond else set(cond["enum"])
    assert methods == covered
    for name, sub in schema["$defs"].items():
        if name.startswith("p_"):
            assert sub.get("additionalProperties") is False, name
            assert {"schema_version", "correlation_id"} <= set(sub["required"]), name
