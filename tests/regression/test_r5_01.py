"""R5-01 (P1; reopens A3-02): classification survives every transformation - correction, answer,
outbox notification, acknowledgement echo and legacy rows. Asserts on the bytes that reached the
(recording) provider, not only on table state. Positive controls keep the product usable.
"""

from __future__ import annotations

from runtime.tasks.state_machine import TaskState
from runtime.verification.verifier import DeliverableSpec
from storage.db import transaction
from tests.regression.r5_harness import R5World, decision

TASK_CONSENT = {"provider": "openai", "purposes": ["task"]}
CHAT_CONSENT = {"provider": "openai", "purposes": ["conversation"]}


def _correct(r5: R5World, sentinel: str) -> str:
    tid = r5.create("Escreva um relatório de teste sintético.")
    out = r5.send(f"Na verdade, meu diagnóstico é {sentinel}. Inclua isso no relatório.", task_id=tid)
    assert out["intent"] == "correction"
    assert out["message"]["classification"] == "SENSITIVE"
    return tid


def test_sensitive_correction_never_reaches_the_provider_without_consent(r5: R5World) -> None:
    sentinel = "SENTINELA_CORRECAO_91837"
    tid = _correct(r5, sentinel)
    out = r5.runner.run(tid, DeliverableSpec())
    assert sentinel not in r5.provider.sent()
    assert out.state == TaskState.WAITING_USER  # asks for consent instead of leaking or guessing
    assert r5.tasks.instructions(tid)[-1]["classification"] == "SENSITIVE"
    assert r5.tasks.get(tid)["data_policy"] == "SENSITIVE"


def test_sensitive_correction_is_sent_only_under_the_exact_consent(r5: R5World) -> None:
    sentinel = "SENTINELA_CORRECAO_55120"
    tid = _correct(r5, sentinel)
    r5.consent(CHAT_CONSENT)  # consent for another purpose does not count
    r5.runner.run(tid, DeliverableSpec())
    assert sentinel not in r5.provider.sent()

    tid2 = _correct(r5, sentinel)
    r5.consent(TASK_CONSENT)
    r5.runner.run(tid2, DeliverableSpec())
    assert sentinel in r5.provider.sent()  # the owner granted exactly this purpose
    assert r5.provider.calls[-1].classification == "SENSITIVE"

    r5.consent()  # revocation is effective on the next emission
    before = len(r5.provider.calls)
    r5.tasks.transition(
        tid2, TaskState.READY, expected_version=r5.tasks.get(tid2)["version"], actor=r5.owner, reason="retry"
    )
    r5.runner.run(tid2, DeliverableSpec())
    assert len(r5.provider.calls) == before


def test_sensitive_answer_never_reaches_the_provider(r5: R5World) -> None:
    sentinel = "SENTINELA_RESPOSTA_8516"
    tid = r5.create("Escreva um relatório de teste sintético.")
    q = r5.waiting_question(tid)
    out = r5.send(f"Meu diagnóstico é {sentinel}", reply_to_message_id=q["message_id"])
    assert out["intent"] == "answer" and out["message"]["classification"] == "SENSITIVE"
    r5.runner.run(tid, DeliverableSpec())
    assert sentinel not in r5.provider.sent()
    assert r5.state(tid) == TaskState.WAITING_USER


def test_outbox_notification_keeps_the_task_classification(r5: R5World) -> None:
    sentinel = "SENTINELA_OUTBOX_73825"
    tid = _correct(r5, "SENTINELA_ORIGEM_1")  # the task became sensitive through a correction
    r5.runner._prepare(tid)
    lease = r5.tasks.acquire_lease(tid, "w")
    r5.tasks.release(lease, TaskState.WAITING_USER, "q", notice=("question", f"Confirma {sentinel}?", None))
    r5.runner._deliver(tid)
    row = r5.conn.execute(
        "SELECT classification, source_ref FROM messages WHERE content LIKE ?", (f"%{sentinel}%",)
    ).fetchone()
    assert row[0] == "SENSITIVE" and row[1] and row[1].startswith(f"task:{tid}")
    r5.provider.reply = {"intent": "chat", "reply": "Oi.", "objective": ""}
    out = r5.send("Qual é a capital da França?")  # a question is never taken as the pending answer
    assert out["intent"] == "chat"  # conversation still works...
    assert sentinel not in r5.provider.sent()  # ...without the sensitive notification


def test_outbox_of_a_sensitive_data_policy_task(r5: R5World) -> None:
    """The reviewer's exact variant: data_policy raised directly, notice enqueued with no class."""
    from runtime.notifications.outbox import OutboxDispatcher, enqueue_in_txn

    sentinel = "SENTINELA_OUTBOX_40017"
    tid = r5.create("Escreva relatório de teste sintético.")
    with transaction(r5.conn):
        r5.conn.execute("UPDATE tasks SET data_policy='SENSITIVE' WHERE id=?", (tid,))
        enqueue_in_txn(r5.conn, r5.clock, employee_id=r5.emp.id, task_id=tid, kind="result", content=sentinel)
    OutboxDispatcher(r5.conn, r5.clock).deliver_pending()
    r5.provider.reply = {"intent": "chat", "reply": "Oi.", "objective": ""}
    r5.send("Olá novamente")
    assert sentinel not in r5.provider.sent()


def test_acknowledgement_echo_of_a_sensitive_request_is_protected(r5: R5World) -> None:
    sentinel = "SENTINELA_ECO_60311"
    out = r5.send(f"Organize os exames do meu filho {sentinel}", intent="delegate")
    assert out["intent"] == "delegate"
    assert out["reply"]["classification"] == "SENSITIVE"  # the ack quotes the request
    r5.provider.reply = {"intent": "chat", "reply": "Oi.", "objective": ""}
    r5.send("Qual é a capital da França")
    r5.send("status")
    assert r5.provider.calls, "the positive control needs a real call"
    assert sentinel not in r5.provider.sent()
    status = r5.conn.execute("SELECT classification FROM messages WHERE kind = 'status' AND role = 'employee'").fetchone()
    assert status[0] == "SENSITIVE"  # the status reply lists the sensitive objective


def test_legacy_rows_without_metadata_are_not_downgraded(r5: R5World) -> None:
    sentinel = "SENTINELA_LEGADO_2231"
    tid = r5.create("Escreva um relatório de teste sintético.")
    with transaction(r5.conn):  # a pre-0020 revision: no classification recorded
        r5.conn.execute(
            "INSERT INTO task_instruction_versions(task_id, revision, kind, instruction, material, author, created_at,"
            " classification) VALUES (?,2,'CORRECTION',?,1,'legacy','2026-01-01T00:00:00.000Z',NULL)",
            (tid, f"meu diagnóstico é {sentinel}"),
        )
        r5.conn.execute("UPDATE tasks SET instruction_revision = 2 WHERE id = ?", (tid,))
    assert r5.tasks.instructions(tid)[-1]["classification"] == "SENSITIVE"
    r5.runner.run(tid, DeliverableSpec())
    assert sentinel not in r5.provider.sent()


def test_positive_controls(r5: R5World) -> None:
    """The initial sensitive message stays blocked; ordinary work still reaches the model."""
    out = r5.send("Meu diagnóstico é SENTINELA_CONTROLE_81921")
    assert out["intent"] == "chat_blocked_sensitive" and not r5.provider.calls
    tid = r5.create("Escreva um relatório sobre maçãs.")
    r5.provider.reply = decision("ask_owner", question="Quantas páginas?")
    r5.runner.run(tid, DeliverableSpec())
    assert "maçãs" in r5.provider.sent()
    assert "SENTINELA_CONTROLE_81921" not in r5.provider.sent()
