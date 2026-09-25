"""R5-07 (P2; reopens A3-12/A3-14/A3-15): files sent as the answer to a question become inputs of THAT
task in the same commit as the answer and the return to READY, with a revision naming them. Resends
are idempotent, another task's question is never used, and the worker really reads the new file.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.tasks.state_machine import TaskState
from runtime.verification.verifier import DeliverableSpec
from shared.errors import AtlasError
from shared.ids import new_id
from tests.regression.r5_harness import R5World, decision


def _links(r5: R5World, tid: str) -> set[str]:
    return {
        r[0]
        for r in r5.conn.execute(
            "SELECT artifact_id FROM artifact_links WHERE task_id = ? AND relation = 'input'", (tid,)
        )
    }


def test_answer_with_one_and_several_files_links_them_before_ready(r5: R5World) -> None:
    tid = r5.create("Compare a proposta que vou enviar.")
    q = r5.waiting_question(tid, "Pode enviar a proposta?")
    a = r5.import_text("Proposta sintética A: preço 100, prazo 3 dias.", name="a.txt")
    b = r5.import_text("Proposta sintética B: preço 120, prazo 2 dias.", name="b.txt")
    out = r5.send("Seguem as propostas.", reply_to_message_id=q["message_id"], artifact_ids=[a.id, b.id])
    assert out["intent"] == "answer" and out["attachments"] == 2
    assert _links(r5, tid) == {a.id, b.id}
    assert r5.state(tid) == TaskState.READY
    last = r5.tasks.instructions(tid)[-1]
    assert last["kind"] == "ATTACHMENT" and a.id in last["instruction"] and b.id in last["instruction"]
    assert last["source_message_id"] == out["message"]["message_id"]


def test_answer_with_only_a_file_and_no_text(r5: R5World) -> None:
    tid = r5.create("Compare a proposta que vou enviar.")
    q = r5.waiting_question(tid)
    a = r5.import_text("Proposta sintética: preço 100.", name="so_arquivo.txt")
    out = r5.send("", reply_to_message_id=q["message_id"], artifact_ids=[a.id])
    assert out["intent"] == "answer" and _links(r5, tid) == {a.id}
    assert r5.state(tid) == TaskState.READY


def test_resend_is_idempotent_and_atomic(r5: R5World) -> None:
    tid = r5.create("Compare a proposta que vou enviar.")
    q = r5.waiting_question(tid)
    a = r5.import_text("Proposta sintética: preço 100.", name="a.txt")
    p = {"conversation_id": r5.cid, "client_message_id": new_id(), "text": "Segue.",
         "reply_to_message_id": q["message_id"], "artifact_ids": [a.id]}
    # A failure inside the operation leaves NOTHING half-done (no link without READY or vice versa).
    real = r5.conv.tasks.transition_in_txn

    def boom(*args: Any, **kw: Any) -> Any:
        raise OSError("injected failure before commit")

    r5.conv.tasks.transition_in_txn = boom  # type: ignore[method-assign]
    with pytest.raises(OSError):
        r5.conv.handle(r5.owner, r5.emp.id, dict(p))
    r5.conv.tasks.transition_in_txn = real  # type: ignore[method-assign]
    assert _links(r5, tid) == set() and r5.state(tid) == TaskState.WAITING_USER
    assert r5.tasks.get(tid)["instruction_revision"] == 1
    first = r5.conv.handle(r5.owner, r5.emp.id, dict(p))  # resent: processed once
    again = r5.conv.handle(r5.owner, r5.emp.id, dict(p))
    assert first["intent"] == "answer" and again["duplicate"] and again["task_id"] == tid
    assert r5.tasks.get(tid)["instruction_revision"] == 2  # one revision, not two
    assert r5.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1  # no extra task
    assert r5.conn.execute("SELECT COUNT(*) FROM artifacts WHERE name = 'a.txt'").fetchone()[0] == 1  # no copy


def test_resumed_after_commit_is_not_reported_as_rejected(r5: R5World) -> None:
    tid = r5.create("Compare a proposta que vou enviar.")
    q = r5.waiting_question(tid)
    a = r5.import_text("Proposta sintética: preço 100.", name="a.txt")
    p = {"conversation_id": r5.cid, "client_message_id": new_id(), "text": "Segue.",
         "reply_to_message_id": q["message_id"], "artifact_ids": [a.id]}
    real = r5.conv._answer_ack

    def crash_after_commit(*args: Any, **kw: Any) -> Any:
        raise OSError("crash after the answer committed, before the reply")

    r5.conv._answer_ack = crash_after_commit  # type: ignore[method-assign]
    with pytest.raises(OSError):
        r5.conv.handle(r5.owner, r5.emp.id, dict(p))
    r5.conv._answer_ack = real  # type: ignore[method-assign]
    out = r5.conv.handle(r5.owner, r5.emp.id, dict(p))
    assert out["intent"] == "answer" and _links(r5, tid) == {a.id}


def test_answer_cannot_target_another_task(r5: R5World) -> None:
    t1 = r5.create("Compare a proposta que vou enviar.")
    t2 = r5.create("Escreva um relatório sobre maçãs.")
    q1 = r5.waiting_question(t1)
    a = r5.import_text("Proposta sintética: preço 100.", name="a.txt")
    with pytest.raises(AtlasError):
        r5.send("Segue.", reply_to_message_id=q1["message_id"], artifact_ids=[a.id], task_id=t2)
    assert _links(r5, t2) == set() and _links(r5, t1) == set()


def test_worker_reads_the_file_received_as_answer(r5: R5World) -> None:
    tid = r5.create("Resuma a proposta que vou enviar.")
    q = r5.waiting_question(tid, "Pode enviar a proposta?")
    a = r5.import_text("Proposta sintética: preço R$ 100,00 e prazo de 3 dias. " * 5, name="proposta.txt")
    r5.send("Segue a proposta.", reply_to_message_id=q["message_id"], artifact_ids=[a.id])

    def step(req: Any) -> dict[str, Any]:
        payload = "\n".join(m.content for m in req.messages)
        assert a.id in payload  # the worker is told about the file received with the answer
        done = r5.conn.execute(
            "SELECT COUNT(*) FROM document_reads WHERE task_id = ? AND artifact_id = ?", (tid, a.id)
        ).fetchone()[0]
        if not done:
            return decision("tool", tool_id="documents.read", input_json=json.dumps({"artifact_id": a.id, "cursor": 0}))
        return decision("ask_owner", question="Li a proposta. Quer o resumo em PDF?")

    r5.provider.reply = step
    r5.runner.run(tid, DeliverableSpec())
    read = r5.conn.execute(
        "SELECT COUNT(*) FROM actions WHERE task_id = ? AND tool_id = 'documents.read' AND status = 'CONFIRMED'"
        " AND instr(input_json, ?) > 0",
        (tid, a.id),
    ).fetchone()[0]
    assert read == 1
