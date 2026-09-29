"""Validate the single task registry; --foundation also verifies the actual Git lineage.

Read-only. No user data, credentials, inference, installations or automatic merges.
A PASS is a foundation check, not acceptance of the complete Atlas product.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "720be87af40ab7d94dfc756c4780800da1b1f5bd"
ALLOWED = frozenset({
    "AGENTS.md", "README.md", "docs/PROGRESS.md", "project/README.md",
    "project/state.json", "project/lineage.json", "scripts/check_consolidation.py",
    "tests/regression/test_project_consolidation.py", ".github/workflows/consolidation.yml",
})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(state: dict[str, Any], lineage: dict[str, Any], backlog: dict[str, Any],
             scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    require(state["schema_version"] == 1 and lineage["schema_version"] == 1, "unsupported schema")
    require(state["repository"] == "ViniciusMilanez82/atlas", "wrong repository")
    require(state["canonical_branch"] == "integration/atlas-base-unificada", "wrong canonical branch")
    require(state["baseline_commit"] == lineage["baseline_commit"] == BASELINE, "baseline mismatch")
    require(state["complete_product"] is False, "task 1 cannot declare the complete product")
    require(state["roles_are_running_agents"] is False, "role allocation is not agent execution")
    require(lineage["userdata_touched"] is False and lineage["unchanged_runtime"] is True,
            "consolidation must not change runtime or owner data")
    require(set(lineage["foundation_allowed_changes"]) == ALLOWED, "changed-file policy mismatch")
    tasks = state["tasks"]
    require(len(tasks) == 12 and {t["id"] for t in tasks} == set(range(1, 13)), "need 12 unique tasks")
    require(all(type(t["id"]) is int for t in tasks), "task id must be an integer")
    roles = state["roles"]
    require("coordinator" in roles and all(isinstance(v, str) and v.strip() for v in roles.values()),
            "invalid roles")
    expected = {f"A3-{i:02d}" for i in range(1, 33)} | {f"N{i:02d}" for i in range(1, 25)}
    items = {i["id"]: i for i in backlog["items"]}
    require(set(items) == expected and len(backlog["items"]) == 56, "normative backlog changed")
    scenario_ids = {s["id"] for s in scenarios}
    require(len(scenarios) == 40 and scenario_ids == {f"T{i:02d}" for i in range(1, 41)},
            "normative scenarios changed")
    assigned: list[str] = []
    graph = {}
    for task in tasks:
        require(task["owner"] in roles, f"unknown owner on task {task['id']}")
        require(task["state"] in {"implemented", "partial", "blocked", "not_implemented"}, "invalid state")
        require(isinstance(task["title"], str) and bool(task["title"].strip()), "missing title")
        require(isinstance(task["acceptance"], str) and bool(task["acceptance"].strip()), "missing acceptance")
        deps = task["depends_on"]
        require(all(type(d) is int and d in range(1, 13) and d != task["id"] for d in deps),
                "invalid dependency")
        require(len(deps) == len(set(deps)), "duplicate dependency")
        graph[task["id"]] = deps
        owned = task["contract_items"]
        require(bool(owned) and all(i in items for i in owned), "unknown or empty contract items")
        assigned.extend(owned)
        covered = {s for i in owned for s in items[i].get("scenarios", [])}
        require(set(task["scenarios"]) == covered and len(task["scenarios"]) == len(covered),
                "scenario mapping differs from normative backlog")
    require(Counter(assigned) == Counter(expected), "contract item missing or assigned twice")
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(task_id: int) -> None:
        require(task_id not in visiting, "dependency cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in graph[task_id]:
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)
    policy = state["write_policy"]
    require(policy["single_writer_per_path"] is True and policy["claim_before_edit"] is True
            and policy["shared_files_owner"] == "coordinator", "single-writer policy missing")
    claimed: set[str] = set()
    by_id = {t["id"]: t for t in tasks}
    for entry in state["active_assignments"]:
        require(entry["task"] in by_id, "assignment has unknown task")
        require(entry["owner"] == by_id[entry["task"]]["owner"], "assignment owner mismatch")
        require(bool(entry["write_paths"]), "assignment needs exact file paths")
        for name in entry["write_paths"]:
            p = PurePosixPath(name)
            require(bool(p.parts) and p.parts[0] != ".git" and not p.is_absolute() and ".." not in p.parts and str(p) == name
                    and not any(c in name for c in "*?[]\\") and not name.endswith("/"), "unsafe write path")
            require(not any(p == PurePosixPath(old) or p in PurePosixPath(old).parents
                            or PurePosixPath(old) in p.parents for old in claimed), "overlapping write claims")
            claimed.add(name)
    for entry in [*lineage["included_ancestors"], *lineage["excluded_heads"]]:
        require(re.fullmatch(r"[a-f0-9]{40}", entry["commit"]) is not None, "invalid commit id")
    return {"scope": "task_1_registry_only", "tasks": 12, "contract_items": 56, "scenarios": 40,
            "active_assignments": len(state["active_assignments"]), "complete_product": False}


def git(root: Path, *args: str, expected: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=False)
    require(result.returncode in expected, f"git check failed: {args[0]}")
    return result


def verify_foundation(root: Path, lineage: dict[str, Any]) -> dict[str, Any]:
    """For task 1 ONLY: require unchanged production code and the genuine, full Git history."""
    require(git(root, "rev-parse", f"{BASELINE}^{{tree}}").stdout.strip() == lineage["baseline_tree"],
            "baseline tree does not match")
    require(git(root, "rev-parse", "refs/remotes/origin/main").stdout.strip() == lineage["main_snapshot"],
            "main changed: revalidate before accepting this consolidation")
    for entry in lineage["included_ancestors"]:
        git(root, "merge-base", "--is-ancestor", entry["commit"], "HEAD")
    for entry in lineage["excluded_heads"]:
        git(root, "cat-file", "-e", entry["commit"])
        result = git(root, "merge-base", "--is-ancestor", entry["commit"], "HEAD", expected=(0, 1))
        require(result.returncode == 1, "an excluded head was included")
    paths = set(filter(None, git(root, "diff", "--name-only", BASELINE, "HEAD").stdout.splitlines()))
    require(paths <= ALLOWED, "unexpected runtime/test/build/contract changes in foundation")
    for name in ("AGENTS.md", "README.md", "docs/PROGRESS.md"):
        previous = git(root, "show", f"{BASELINE}:{name}").stdout
        require((root / name).read_text().endswith(previous), "historical source was not preserved")
    require(not git(root, "status", "--porcelain", "--untracked-files=all").stdout.strip(),
            "foundation worktree is not clean")
    return {"head": git(root, "rev-parse", "HEAD").stdout.strip(), "base": BASELINE,
            "changed_files": sorted(paths), "runtime_unchanged": True, "lineage_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation", action="store_true")
    args = parser.parse_args()
    try:
        state = json.loads((ROOT / "project/state.json").read_text())
        lineage = json.loads((ROOT / "project/lineage.json").read_text())
        backlog = json.loads((ROOT / lineage["normative_backlog"]).read_text())
        scenarios = json.loads((ROOT / lineage["normative_scenarios"]).read_text())
        report = validate(state, lineage, backlog, scenarios)
        if args.foundation:
            report["foundation"] = verify_foundation(ROOT, lineage)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
