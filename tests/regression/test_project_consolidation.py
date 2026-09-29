"""Task 1 metadata regressions. Actual lineage/build checks belong to macOS/Linux CI."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_consolidation import validate

ROOT = Path(__file__).resolve().parents[2]


def documents() -> tuple[Any, Any, Any, Any]:
    return tuple(json.loads((ROOT / p).read_text()) for p in (
        "project/state.json", "project/lineage.json", "docs/spec/v2/BACKLOG_EXECUTAVEL.json",
        "docs/spec/v2/CENARIOS_ACEITE.json"))


def test_actual_registry_covers_all_contract_items_and_scenarios() -> None:
    report = validate(*documents())
    assert (report["tasks"], report["contract_items"], report["scenarios"]) == (12, 56, 40)
    assert report["complete_product"] is False


@pytest.mark.parametrize("case", [
    "missing_task", "duplicate_task", "unknown_owner", "unknown_state", "missing_acceptance",
    "unknown_dependency", "self_dependency", "cycle", "duplicate_contract", "missing_contract",
    "unknown_contract", "scenario_omitted", "scenario_duplicate", "false_completion", "fake_agents",
    "wrong_baseline", "changed_runtime", "touched_userdata", "changed_allowlist", "missing_policy",
    "wrong_assignment_owner", "two_writers", "absolute_path", "parent_path", "wildcard_path",
    "missing_scenario", "changed_contract", "bad_commit",
])
def test_invalid_project_state_fails_closed(case: str) -> None:
    state, lineage, backlog, scenarios = copy.deepcopy(documents())
    tasks = state["tasks"]
    if case == "missing_task":
        tasks.pop()
    elif case == "duplicate_task":
        tasks[-1]["id"] = 1
    elif case == "unknown_owner":
        tasks[0]["owner"] = "invented"
    elif case == "unknown_state":
        tasks[0]["state"] = "finished_everything"
    elif case == "missing_acceptance":
        tasks[0]["acceptance"] = ""
    elif case == "unknown_dependency":
        tasks[0]["depends_on"] = [999]
    elif case == "self_dependency":
        tasks[0]["depends_on"] = [1]
    elif case == "cycle":
        tasks[0]["depends_on"] = [2]
    elif case == "duplicate_contract":
        tasks[1]["contract_items"].append("N01")
    elif case == "missing_contract":
        tasks[2]["contract_items"].remove("N02")
    elif case == "unknown_contract":
        tasks[0]["contract_items"] = ["N99"]
    elif case == "scenario_omitted":
        tasks[-1]["scenarios"].pop()
    elif case == "scenario_duplicate":
        tasks[-1]["scenarios"].append("T01")
    elif case == "false_completion":
        state["complete_product"] = True
    elif case == "fake_agents":
        state["roles_are_running_agents"] = True
    elif case == "wrong_baseline":
        state["baseline_commit"] = "a" * 40
    elif case == "changed_runtime":
        lineage["unchanged_runtime"] = False
    elif case == "touched_userdata":
        lineage["userdata_touched"] = True
    elif case == "changed_allowlist":
        lineage["foundation_allowed_changes"].append("core/service.py")
    elif case == "missing_policy":
        state["write_policy"]["claim_before_edit"] = False
    elif case == "missing_scenario":
        scenarios.pop()
    elif case == "changed_contract":
        backlog["items"].pop()
    elif case == "bad_commit":
        lineage["included_ancestors"][0]["commit"] = "not-a-commit"
    else:
        entry = {"task": 2, "owner": "intelligence", "write_paths": ["core/intelligence.py"]}
        state["active_assignments"] = [entry]
        if case == "wrong_assignment_owner":
            entry["owner"] = "coordinator"
        elif case == "two_writers":
            state["active_assignments"].append(copy.deepcopy(entry))
        elif case == "absolute_path":
            entry["write_paths"] = ["/private/file"]
        elif case == "parent_path":
            entry["write_paths"] = ["../file"]
        elif case == "wildcard_path":
            entry["write_paths"] = ["core/*.py"]
    with pytest.raises((ValueError, KeyError)):
        validate(state, lineage, backlog, scenarios)


def test_nonconflicting_assignments_are_valid() -> None:
    state, lineage, backlog, scenarios = documents()
    state["active_assignments"] = [
        {"task": 2, "owner": "intelligence", "write_paths": ["core/intelligence.py"]},
        {"task": 11, "owner": "security_review", "write_paths": ["security/egress/guard.py"]},
    ]
    assert validate(state, lineage, backlog, scenarios)["active_assignments"] == 2
