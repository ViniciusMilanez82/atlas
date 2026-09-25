"""R5-04 (P1; reopens A3-03/A3-07): a decision, its verification and the COMPLETED commit are bound to
the instruction revision they were made for. A correction during inference, or between verification
and commit, never lets the old deliverable complete; evidence declares the revision it evaluated.
"""

from __future__ import annotations

from typing import Any

from runtime.tasks.state_machine import TaskState
from runtime.verification.verifier import DeliverableSpec, Verifier
from tests.regression.r5_harness import R5World, decision

APPLES = "Maçãs vermelhas. " + "As maçãs vermelhas são descritas neste relatório como exemplo sintético para os testes. " * 4
BANANAS = "Bananas amarelas. " + "As bananas amarelas são descritas neste relatório como exemplo sintético para os testes. " * 4
CORRECTION = "Na verdade, abandone as maçãs e produza o relatório somente sobre bananas amarelas."


def test_old_finish_after_a_correction_during_inference_does_not_complete(r5: R5World) -> None:
    tid = r5.create("Escreva um relatório sobre maçãs vermelhas.")
    old = r5.artifact(tid, APPLES)
    r5.provider.reply = decision("finish", artifact_id=old.id)

    def correct(_: Any) -> None:
        r5.provider.hook = None
        r5.tasks.update_instruction(tid, actor=r5.owner, text=CORRECTION)

    r5.provider.hook = correct
    out = r5.runner.run(tid, DeliverableSpec())
    assert out.state != TaskState.COMPLETED
    assert r5.tasks.get(tid)["instruction_revision"] == 2
    # The model saw the new revision before anything could complete.
    assert CORRECTION in "\n".join(m.content for m in r5.provider.calls[-1].messages)


def test_the_right_deliverable_completes_with_evidence_of_the_revision(r5: R5World) -> None:
    tid = r5.create("Escreva um relatório sobre maçãs vermelhas.")
    r5.tasks.update_instruction(tid, actor=r5.owner, text=CORRECTION)
    new = r5.artifact(tid, BANANAS, name="bananas.txt")
    r5.provider.reply = decision("finish", artifact_id=new.id)
    out = r5.runner.run(tid, DeliverableSpec())
    assert out.state == TaskState.COMPLETED, out.gaps
    revs = {r[0] for r in r5.conn.execute(
        "SELECT e.instruction_revision FROM task_criteria c JOIN evidence e ON e.id = c.evidence_id"
        " WHERE c.task_id = ? AND c.superseded_revision IS NULL", (tid,))}
    assert revs == {2}  # every satisfied criterion names the revision it evaluated
    notice = r5.conn.execute(
        "SELECT source_ref FROM notification_outbox WHERE task_id = ? AND kind = 'result'", (tid,)
    ).fetchone()
    assert notice[0] == f"task:{tid}:rev2"  # completion and outbox reference the same revision


def test_old_apples_deliverable_fails_after_the_correction(r5: R5World) -> None:
    tid = r5.create("Escreva um relatório sobre maçãs vermelhas.")
    r5.tasks.update_instruction(tid, actor=r5.owner, text=CORRECTION)
    res = r5.verifier.verify_text_artifact(tid, r5.artifact(tid, APPLES).id, DeliverableSpec())
    assert not res.passed and any("banan" in g for g in res.gaps)


def test_correction_between_verification_and_commit(r5: R5World) -> None:
    tid = r5.create("Escreva um relatório sobre maçãs vermelhas.")
    old = r5.artifact(tid, APPLES)
    r5.provider.reply = decision("finish", artifact_id=old.id)
    real = r5.verifier.verify_text_artifact

    def verify_then_correct(task_id: str, artifact_id: str, spec: DeliverableSpec) -> Any:
        result = real(task_id, artifact_id, spec)  # passes for the apples revision...
        r5.tasks.update_instruction(tid, actor=r5.owner, text=CORRECTION)  # ...then the owner corrects
        return result

    r5.runner.verifier = Verifier.__new__(Verifier)
    r5.runner.verifier.__dict__.update(r5.verifier.__dict__)
    r5.runner.verifier.verify_text_artifact = verify_then_correct  # type: ignore[method-assign]
    out = r5.runner.run(tid, DeliverableSpec())
    assert r5.state(tid) != TaskState.COMPLETED, out
    assert r5.state(tid) in (TaskState.READY, TaskState.RUNNING, TaskState.BLOCKED, TaskState.WAITING_USER)


def test_cap_change_and_new_attachment_invalidate_old_evidence(r5: R5World) -> None:
    req = "Compare fornecedores de módulos e não ultrapasse R$ 8.000 no total."
    tid = r5.create(req)
    body = (
        "Comparação de fornecedores de módulos. Fornecedor A: total R$ 6.900,00. Fornecedor B: total R$ 7.400,00. "
        "Recomendo o fornecedor A, total R$ 6.900,00, dentro do teto. " * 2
    )
    art = r5.artifact(tid, body)
    assert r5.verifier.verify_text_artifact(tid, art.id, DeliverableSpec()).passed
    r5.tasks.update_instruction(tid, actor=r5.owner, text="Na verdade, o teto agora é de até R$ 5.000 no total.")
    res = r5.verifier.verify_text_artifact(tid, art.id, DeliverableSpec())
    assert not res.passed and any("5.000" in g for g in res.gaps)
    # Raising the cap supersedes the stricter one instead of stacking contradictory conditions.
    r5.tasks.update_instruction(tid, actor=r5.owner, text="Na verdade, o teto agora é de até R$ 10.000 no total.")
    res = r5.verifier.verify_text_artifact(tid, art.id, DeliverableSpec())
    assert not any("5.000" in g for g in res.gaps), res.gaps
    # A new attachment requires reading it before completion.
    doc = r5.import_text("Proposta do fornecedor C: total R$ 4.000,00.", task_id=None)
    with r5.conn:
        r5.conn.execute("INSERT INTO artifact_links(artifact_id, task_id, relation) VALUES (?,?,'input')", (doc.id, tid))
    r5.tasks.update_instruction(tid, actor=r5.owner, text=f"Considere também o anexo {doc.id}.", kind="ATTACHMENT")
    res = r5.verifier.verify_text_artifact(tid, art.id, DeliverableSpec())
    assert not res.passed and any("não foram lidos" in g or "lido" in g for g in res.gaps)


def test_non_material_note_keeps_evidence_with_a_recorded_justification(r5: R5World) -> None:
    tid = r5.create("Escreva um relatório sobre maçãs vermelhas.")
    art = r5.artifact(tid, APPLES)
    res = r5.verifier.verify_text_artifact(tid, art.id, DeliverableSpec())
    for cid, cr in res.criteria.items():
        r5.tasks.satisfy_criterion(tid, cid, cr.evidence_id or "")
    r5.tasks.update_instruction(tid, actor=r5.owner, text="Obrigado!", material=False)
    kept = r5.conn.execute(
        "SELECT COUNT(*) FROM task_criteria WHERE task_id = ? AND satisfied_at IS NOT NULL", (tid,)
    ).fetchone()[0]
    assert kept == len(res.criteria)
    j = r5.conn.execute(
        "SELECT summary FROM journal_events WHERE task_id = ? AND type = 'task.instruction_updated'"
        " ORDER BY rowid DESC LIMIT 1", (tid,)
    ).fetchone()[0]
    assert "evidence kept" in j
