"""M11 / spec 15.2-15.3: a false 'done' and a missing file are rejected; real evidence completes."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.artifacts.manager import ArtifactManager
from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from runtime.verification.verifier import DeliverableSpec, Verifier
from shared.actors import Actor
from shared.errors import AtlasError
from shared.ids import new_id
from tests.conftest import World

RT = Actor("runtime", "rt")
GOOD = (
    "# Comparacao das propostas\n\nA proposta A custa menos e entrega em 10 dias. A proposta B oferece garantia "
    "maior. Recomendacao: A, pelo prazo e custo, salvo se a garantia estendida for decisiva.\n\n"
    "Fontes: artifact:{a} e artifact:{b}\n"
)


@pytest.fixture
def env(world: World, tmp_path: Path) -> tuple[ArtifactManager, Verifier, TaskEngine, str]:
    am = ArtifactManager(world.conn, world.clock, tmp_path / "store")
    engine = TaskEngine(world.conn, world.clock)
    tid = engine.create(
        world.owner,
        employee_id=world.employee.id,
        objective="Comparar propostas",
        criteria=[("Relatorio verificado com fontes", True)],
    )
    return am, Verifier(world.conn, world.clock, am), engine, tid


def _inputs(world: World, am: ArtifactManager, tid: str, tmp: Path) -> tuple[str, str]:
    """Two real inputs of the task, read by the task (A3-07: a cited source must exist and be consulted)."""
    from storage.db import transaction

    ids = []
    for name in ("a.txt", "b.txt"):
        f = tmp / name
        f.write_text(f"proposta {name}", encoding="utf-8")
        ids.append(am.import_file(f, actor=world.owner, employee_id=world.employee.id, task_id=tid).id)
    with transaction(world.conn):
        for aid in ids:
            world.conn.execute(
                "INSERT INTO document_reads(task_id, artifact_id, seq, read_at)"
                " VALUES (?,?,0,'2026-01-01T00:00:00.000Z')",
                (tid, aid),
            )
    return ids[0], ids[1]


SPEC = DeliverableSpec(
    min_chars=120, required_terms=("proposta A", "proposta B", "recomendacao"), min_sources=2
)


def test_good_report_passes_and_produces_evidence(
    env: tuple[ArtifactManager, Verifier, TaskEngine, str], world: World, tmp_path: Path
) -> None:
    am, ver, _, tid = env
    a, b = _inputs(world, am, tid, tmp_path)
    art = am.create_text(
        actor=RT,
        employee_id=world.employee.id,
        task_id=tid,
        name="relatorio.md",
        content=GOOD.format(a=a, b=b),
    )
    res = ver.verify_text_artifact(tid, art.id, SPEC)
    assert res.passed, res.gaps
    assert (
        world.conn.execute("SELECT kind FROM evidence WHERE id=?", (res.evidence_id,)).fetchone()[0]
        == "file_opens"
    )


@pytest.mark.parametrize(
    ("content", "gap"),
    [
        ("Pronto! Revisei e esta tudo certo.", "too short"),
        (GOOD.replace("A proposta B oferece", "TODO: comparar a proposta B que oferece"), "placeholders"),
        (GOOD.replace("Recomendacao", "Conclusao"), "missing required content"),
        (GOOD.replace("artifact:{b}", "o outro documento"), "fonte"),
    ],
)
def test_incomplete_reports_are_rejected(
    env: tuple[ArtifactManager, Verifier, TaskEngine, str], world: World, content: str, gap: str, tmp_path: Path
) -> None:
    am, ver, _, tid = env
    a, b = _inputs(world, am, tid, tmp_path)
    art = am.create_text(
        actor=RT,
        employee_id=world.employee.id,
        task_id=tid,
        name="r.md",
        content=content.format(a=a, b=b),
    )
    res = ver.verify_text_artifact(tid, art.id, SPEC)
    assert not res.passed and any(gap in g for g in res.gaps), res.gaps
    assert res.evidence_id is None


def test_nonexistent_file_is_rejected(env: tuple[ArtifactManager, Verifier, TaskEngine, str]) -> None:
    _, ver, _, tid = env
    res = ver.verify_text_artifact(tid, new_id(), SPEC)  # the model "wrote" a name that does not exist
    assert not res.passed and not res.checks["exists_and_hash_matches"]


def test_model_claim_cannot_complete_the_task(
    env: tuple[ArtifactManager, Verifier, TaskEngine, str], world: World, tmp_path: Path
) -> None:
    am, ver, engine, tid = env
    a, b = _inputs(world, am, tid, tmp_path)
    for to in (TaskState.UNDERSTANDING, TaskState.PLANNING, TaskState.READY):
        engine.transition(tid, to, expected_version=engine.get(tid)["version"], actor=RT, reason="t")
    engine.release(engine.acquire_lease(tid, "w1"), TaskState.VERIFYING, "model says done")
    with pytest.raises(AtlasError):
        engine.complete(tid, actor=RT, expected_version=engine.get(tid)["version"])  # no evidence
    art = am.create_text(
        actor=RT,
        employee_id=world.employee.id,
        task_id=tid,
        name="relatorio.md",
        content=GOOD.format(a=a, b=b),
    )
    res = ver.verify_text_artifact(tid, art.id, SPEC)
    crit = engine.get(tid)["completion_criteria"][0]["criterion_id"]
    engine.satisfy_criterion(tid, crit, res.criteria[crit].evidence_id)  # type: ignore[arg-type]
    engine.complete(tid, actor=RT, expected_version=engine.get(tid)["version"])
    assert engine.get(tid)["state"] == "COMPLETED"


def test_artifact_of_another_task_does_not_count(
    env: tuple[ArtifactManager, Verifier, TaskEngine, str], world: World
) -> None:
    am, ver, engine, tid = env
    other = engine.create(world.owner, employee_id=world.employee.id, objective="outra")
    art = am.create_text(
        actor=RT,
        employee_id=world.employee.id,
        task_id=other,
        name="r.md",
        content=GOOD.format(a=new_id(), b=new_id()),
    )
    assert not ver.verify_text_artifact(tid, art.id, SPEC).passed
