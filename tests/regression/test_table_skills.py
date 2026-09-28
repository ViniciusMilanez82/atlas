"""Real skill interpreter, SQLite, broker and owner IPC; no file-writing skill. No external model."""
from __future__ import annotations

import json
import sqlite3
from decimal import ROUND_DOWN, localcontext
from typing import Any

import pytest

from runtime.skills import table_engine as engine
from runtime.skills.table_library import TableLibrary
from shared.actors import Actor
from shared.errors import AtlasError
from shared.ids import new_id
from tests.integration.test_alpha2 import Env, ok
from tests.regression.r5_harness import R5World, decision


def spec(price: str = "unit") -> dict[str, Any]:
    return {"format": "atlas.table.v1", "columns": [
        {"name": "item", "op": "strip", "field": "item"},
        {"name": "total", "op": "multiply", "fields": [price, "qty"], "scale": 2}],
        "tests": [
            {"label": "two modules", "rows": [{"item": "A ", price: "100.25", "qty": 2}],
             "expected": [{"item": "A", "total": "200.50"}]},
            {"label": "rounding", "rows": [{"item": " B", price: "1.005", "qty": 1}],
             "expected": [{"item": "B", "total": "1.01"}]}]}


def library(r5: R5World) -> TableLibrary:
    return TableLibrary(r5.conn, r5.clock)


def direct_propose(r5: R5World, definition: dict[str, Any] | None = None, key: str = "module_total") -> dict[str, Any]:
    task = r5.create("Propor uma habilidade de cálculo")
    return library(r5).propose(r5.emp.id, key=key, description="Calcular total por linha.", definition=definition or spec(),
        task_id=task, action_id=new_id(), classification="INTERNAL", check_fence=lambda: None)


def activate_version(r5: R5World, version: dict[str, Any]) -> dict[str, Any]:
    lib = library(r5)
    tested = lib.test(r5.emp.id, version["id"], version["revision"], actor=r5.owner, request_id=new_id())
    return lib.decide(r5.emp.id, tested["id"], actor=r5.owner, expected_revision=tested["revision"],
        content_hash=tested["content_hash"], test_id=tested["test_id"], decision="activate", request_id=new_id())


def run_tool(r5: R5World, task: str, name: str, data: dict[str, Any]) -> Any:
    sent = False
    def reply(_: Any) -> dict[str, Any]:
        nonlocal sent
        if sent:
            return decision(question="Aguardando revisão.")
        sent = True
        return decision("tool", tool_id=name, input_json=json.dumps(data))
    r5.provider.reply = reply
    from runtime.verification.verifier import DeliverableSpec
    return r5.runner.run(task, DeliverableSpec())


def test_decimal_rounding_is_independent_of_ambient_context() -> None:
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.rounding = ROUND_DOWN
        result = engine.execute(spec(), [{"item": "C", "unit": "90071992547409.93", "qty": 3}])
        assert result[0]["total"] == "270215977642229.79"
        assert ctx.prec == 2 and ctx.rounding == ROUND_DOWN


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "1e100", "1,23", "01.00", "-0.001000000", 1.1])
def test_ambiguous_or_nonfinite_numbers_are_not_silently_interpreted(value: Any) -> None:
    with pytest.raises(engine.TableError):
        engine.execute(spec(), [{"item": "X", "unit": value, "qty": 2}])


@pytest.mark.parametrize("op", ["python", "eval", "shell", "read_file", "fetch", "getattr"])
def test_no_executable_or_external_operation_is_accepted(op: str) -> None:
    definition = spec()
    definition["columns"][0]["op"] = op
    with pytest.raises(engine.TableError, match="INVALID_DEFINITION"):
        engine.execute(definition, [])


def test_field_names_are_literal_dictionary_keys_not_access_paths() -> None:
    definition = spec("__class__.__dict__")
    assert engine.execute(definition, [{"item": "X", "__class__.__dict__": "3.20", "qty": 2}])[0]["total"] == "6.40"


def test_no_overwrite_by_duplicate_output_column() -> None:
    definition = spec()
    definition["columns"][1]["name"] = "item"
    with pytest.raises(engine.TableError, match="DUPLICATE_COLUMN"):
        engine.validate_definition(definition)


def test_two_distinct_nonempty_examples_required() -> None:
    definition = spec()
    definition["tests"][1] = definition["tests"][0]
    with pytest.raises(engine.TableError, match="TWO_DISTINCT"):
        engine.validate_definition(definition)


def test_output_and_input_limits_and_cancellation() -> None:
    with pytest.raises(engine.TableError):
        engine.execute(spec(), [{"item": "x", "unit": "1", "qty": 1}] * 2001)
    with pytest.raises(engine.TableError, match="CANCELLED"):
        engine.execute(spec(), [{"item": "x", "unit": "1", "qty": 1}], cancelled=lambda: True)
    definition = spec()
    definition["columns"] = [{"name": f"c{i}", "op": "literal", "value": "x" * 1000} for i in range(30)]
    with pytest.raises(engine.TableError, match="SIZE_LIMIT"):
        engine.execute(definition, [{"a": 1}] * 30)


def test_expected_error_example_checks_actual_error() -> None:
    definition = spec()
    definition["tests"].append({"label": "missing", "rows": [{"item": "X"}], "expected_error": "MISSING_FIELD"})
    assert engine.check_examples(definition)["passed"]
    definition["tests"][-1]["expected_error"] = "DIVIDE_BY_ZERO"
    assert not engine.check_examples(definition)["passed"]


def test_failed_skill_requires_new_version_and_cannot_activate(r5: R5World) -> None:
    bad = spec()
    bad["tests"][0]["expected"][0]["total"] = "999.00"
    first = direct_propose(r5, bad)
    tested = library(r5).test(r5.emp.id, first["id"], 1, actor=r5.owner, request_id=new_id())
    assert tested["state"] == "DRAFT" and not tested["tests_passed"]
    with pytest.raises(AtlasError):
        library(r5).decide(r5.emp.id, first["id"], actor=r5.owner, expected_revision=tested["revision"],
            content_hash=first["content_hash"], test_id=tested["test_id"], decision="activate", request_id=new_id())
    with pytest.raises(sqlite3.IntegrityError):
        r5.conn.execute("UPDATE table_skill_versions SET definition_json='{}' WHERE id=?", (first["id"],))
    second = activate_version(r5, direct_propose(r5))
    assert second["version"] == 2 and second["usable"]
    assert library(r5).get(r5.emp.id, first["id"])["state"] == "DRAFT"


@pytest.mark.parametrize("actor_kind,channel", [("runtime", "internal"), ("owner", "paired_device"), ("owner", "local_app")])
def test_wrong_actors_never_activate(r5: R5World, actor_kind: str, channel: str) -> None:
    version = direct_propose(r5)
    actor = Actor(actor_kind, "wrong-owner" if channel == "local_app" else r5.owner_id, channel)
    with pytest.raises(AtlasError):
        library(r5).decide(r5.emp.id, version["id"], actor=actor, expected_revision=1,
            content_hash=version["content_hash"], test_id=None, decision="activate", request_id=new_id())


def test_restart_catalog_scope_and_rollback_preserve_evidence(r5: R5World) -> None:
    first = activate_version(r5, direct_propose(r5))
    second = activate_version(r5, direct_propose(r5, spec("price")))
    lib = library(r5)
    assert lib.get(r5.emp.id, first["id"])["state"] == "SUPERSEDED"
    assert lib.list("another-employee", active_only=True) == []
    with pytest.raises(AtlasError):
        lib.get("another-employee", first["id"])
    fresh = lib.get(r5.emp.id, first["id"])
    rolled = lib.decide(r5.emp.id, first["id"], actor=r5.owner, expected_revision=fresh["revision"],
        content_hash=fresh["content_hash"], test_id=fresh["test_id"], decision="rollback", request_id=new_id())
    assert rolled["usable"] and lib.get(r5.emp.id, second["id"])["state"] == "SUPERSEDED"
    assert r5.conn.execute("SELECT COUNT(*) FROM table_skill_tests").fetchone()[0] == 2


def test_changed_engine_invalidates_approval(r5: R5World, monkeypatch: pytest.MonkeyPatch) -> None:
    version = activate_version(r5, direct_propose(r5))
    monkeypatch.setattr(engine, "fingerprint", lambda: "different-engine")
    assert library(r5).list(r5.emp.id, active_only=True) == []
    with pytest.raises(AtlasError):
        library(r5).active(r5.emp.id, version["id"], version["content_hash"])


def test_decision_replay_does_not_reactivate_revoked_version(r5: R5World) -> None:
    active = activate_version(r5, direct_propose(r5))
    lib = library(r5)
    rid = new_id()
    kw = dict(actor=r5.owner, expected_revision=active["revision"], content_hash=active["content_hash"],
              test_id=active["test_id"], decision="revoke", request_id=rid)
    first = lib.decide(r5.emp.id, active["id"], **kw)
    replay = lib.decide(r5.emp.id, active["id"], **kw)
    assert first["state"] == replay["state"] == "REVOKED" and replay["replayed"]
    kw["decision"] = "activate"
    with pytest.raises(AtlasError):
        lib.decide(r5.emp.id, active["id"], **kw)


def test_real_broker_proposes_tests_and_waits_for_owner(r5: R5World) -> None:
    task = r5.create("Criar procedimento para calcular total por linha")
    run_tool(r5, task, "skills.propose_table", {"skill_key": "line_total", "description": "Total por linha", "definition": spec()})
    versions = library(r5).list(r5.emp.id)
    assert len(versions) == 1, r5.provider.sent()
    assert versions[0]["state"] == "TESTED" and not versions[0]["usable"]
    assert "owner_review_required" in r5.provider.sent()
    assert r5.conn.execute("SELECT status FROM actions WHERE task_id=?", (task,)).fetchone()[0] == "CONFIRMED"


def test_real_broker_reuses_skill_returns_result_with_hash_and_no_file_write(r5: R5World) -> None:
    version = activate_version(r5, direct_propose(r5))
    task = r5.create("Calcular totais")
    run_tool(r5, task, "skills.transform_rows", {"version_id": version["id"], "content_hash": version["content_hash"], "rows": [{"item": "Nova", "unit": "19.95", "qty": 3}]})
    row = r5.conn.execute("SELECT * FROM table_skill_uses WHERE task_id=?", (task,)).fetchone()
    assert row is not None, r5.provider.sent()
    assert row["error_code"] is None
    observation = r5.conn.execute("SELECT content FROM step_observations WHERE task_id=? ORDER BY rowid LIMIT 1", (task,)).fetchone()[0]
    result = json.loads(observation)
    assert result["rows"] == [{"item": "Nova", "total": "59.85"}]
    assert result["skill_hash"] == version["content_hash"] and result["output_hash"] == row["output_hash"]
    assert r5.conn.execute("SELECT COUNT(*) FROM artifacts WHERE task_id=?", (task,)).fetchone()[0] == 0


def test_no_file_path_or_artifact_parameter_is_accepted(r5: R5World) -> None:
    version = activate_version(r5, direct_propose(r5))
    task = r5.create("Calcular totais")
    run_tool(r5, task, "skills.transform_rows", {"version_id": version["id"], "content_hash": version["content_hash"],
        "rows": [], "path": "/Users/owner/private", "artifact_id": new_id()})
    assert r5.conn.execute("SELECT COUNT(*) FROM table_skill_uses").fetchone()[0] == 0
    assert r5.conn.execute("SELECT COUNT(*) FROM artifacts WHERE task_id=?", (task,)).fetchone()[0] == 0


def test_three_distinct_bad_inputs_quarantine_not_silent_retry(r5: R5World) -> None:
    version = activate_version(r5, direct_propose(r5))
    for _ in range(3):
        task = r5.create("Calcular totais")
        run_tool(r5, task, "skills.transform_rows", {"version_id": version["id"], "content_hash": version["content_hash"], "rows": [{"item": "X"}]})
    result = library(r5).get(r5.emp.id, version["id"])
    assert result["state"] == "QUARANTINED" and result["failure_count"] == 3
    assert len(result["uses"]) == 3


def test_revocation_during_transform_prevents_result_commit(r5: R5World, monkeypatch: pytest.MonkeyPatch) -> None:
    version = activate_version(r5, direct_propose(r5))
    task = r5.create("Calcular totais")
    real = engine.execute
    def interrupt(*args: Any, **kwargs: Any) -> Any:
        from storage.db import connect
        conn = connect(r5.root / "atlas.sqlite")
        try:
            lib = TableLibrary(conn, r5.clock)
            lib.decide(r5.emp.id, version["id"], actor=r5.owner, expected_revision=version["revision"],
                content_hash=version["content_hash"], test_id=version["test_id"], decision="revoke", request_id=new_id())
        finally:
            conn.close()
        return real(*args, **kwargs)
    monkeypatch.setattr(engine, "execute", interrupt)
    run_tool(r5, task, "skills.transform_rows", {"version_id": version["id"], "content_hash": version["content_hash"], "rows": [{"item": "X", "unit": "9", "qty": 1}]})
    assert r5.conn.execute("SELECT COUNT(*) FROM table_skill_uses").fetchone()[0] == 0
    assert r5.conn.execute("SELECT COUNT(*) FROM artifacts WHERE task_id=?", (task,)).fetchone()[0] == 0


def test_owner_ipc_list_and_unknown_version(env: Env) -> None:
    c = env.connect()
    assert ok(c.call("skills.list"))["skills"] == []
    reply = c.call("skills.get", version_id=new_id())
    assert reply["error"]["data"]["atlas_code"] == "INVALID_INPUT"
    forbidden = c.call("skills.decide", version_id=new_id(), expected_revision=1, content_hash="a"*64,
        test_id=None, decision="activate", request_id=new_id(), actor="owner")
    assert forbidden["error"]["data"]["atlas_code"] == "INVALID_INPUT"


@pytest.mark.parametrize("change", ["pause", "instruction"])
def test_task_control_during_transform_prevents_output(r5: R5World, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    version = activate_version(r5, direct_propose(r5))
    task = r5.create("Calcular totais")
    real = engine.execute
    def interrupt(*args: Any, **kwargs: Any) -> Any:
        from runtime.tasks.engine import TaskEngine
        from storage.db import connect
        conn = connect(r5.root / "atlas.sqlite")
        try:
            tasks = TaskEngine(conn, r5.clock)
            if change == "pause":
                tasks.pause(task, actor=r5.owner, expected_version=tasks.get(task)["version"])
            else:
                tasks.update_instruction(task, actor=r5.owner, text="Mude a fórmula antes de apresentar o resultado")
        finally:
            conn.close()
        return real(*args, **kwargs)
    monkeypatch.setattr(engine, "execute", interrupt)
    run_tool(r5, task, "skills.transform_rows", {"version_id": version["id"], "content_hash": version["content_hash"], "rows": [{"item": "X", "unit": "9", "qty": 1}]})
    assert r5.conn.execute("SELECT COUNT(*) FROM table_skill_uses").fetchone()[0] == 0
    assert r5.conn.execute("SELECT COUNT(*) FROM artifacts WHERE task_id=?", (task,)).fetchone()[0] == 0


def test_catalog_sensitive_description_does_not_reach_unconsented_model(r5: R5World) -> None:
    lib = library(r5)
    task = r5.create("Propor habilidade")
    version = lib.propose(r5.emp.id, key="private_total", description="SENSITIVE_SKILL_SENTINEL",
        definition=spec(), task_id=task, action_id=new_id(), classification="SENSITIVE", check_fence=lambda: None)
    activate_version(r5, version)
    next_task = r5.create("Consultar habilidades disponíveis")
    run_tool(r5, next_task, "skills.catalog", {})
    assert "SENSITIVE_SKILL_SENTINEL" not in r5.provider.sent()
    observation = r5.conn.execute("SELECT classification,content FROM step_observations WHERE task_id=?", (next_task,)).fetchone()
    assert observation[0] == "SENSITIVE" and "SENSITIVE_SKILL_SENTINEL" in observation[1]


def test_ipc_denies_paired_and_forged_owner(env: Env) -> None:
    for actor in (Actor("owner", env.world.owner.id, "paired_device"), Actor("owner", "someone-else", "local_app")):
        response = env.connect(actor).call("skills.list")
        assert response["error"]["data"]["atlas_code"] == "UNAUTHORIZED"


def test_all_decisions_bound_to_revision_hash_and_test_id(r5: R5World) -> None:
    first = direct_propose(r5)
    tested = library(r5).test(r5.emp.id, first["id"], 1, actor=r5.owner, request_id=new_id())
    kwargs = {"actor": r5.owner, "expected_revision": tested["revision"], "content_hash": tested["content_hash"],
              "test_id": tested["test_id"], "decision": "activate", "request_id": new_id()}
    for field, bad in (("expected_revision", 1), ("content_hash", "0" * 64), ("test_id", new_id())):
        with pytest.raises(AtlasError):
            library(r5).decide(r5.emp.id, first["id"], **{**kwargs, field: bad})
    assert library(r5).get(r5.emp.id, first["id"])["state"] == "TESTED"


def test_failure_in_decision_receipt_rolls_back_activation(r5: R5World, monkeypatch: pytest.MonkeyPatch) -> None:
    lib = library(r5)
    version = direct_propose(r5)
    tested = lib.test(r5.emp.id, version["id"], 1, actor=r5.owner, request_id=new_id())
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated write failure")
    monkeypatch.setattr(lib, "_receipt", fail)
    with pytest.raises(RuntimeError):
        lib.decide(r5.emp.id, version["id"], actor=r5.owner, expected_revision=tested["revision"],
            content_hash=tested["content_hash"], test_id=tested["test_id"], decision="activate", request_id=new_id())
    assert library(r5).get(r5.emp.id, version["id"])["state"] == "TESTED"
