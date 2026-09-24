"""A3-13 (status/memory false positives), A3-14 (pending question captures new subjects) and A3-15
(an attachment forces delegation) - scenarios T03, T10, T11.

pt-BR corpus with the expected route for each phrase. Real ConversationService over IPC; no model is
configured, so every route below is decided deterministically (the free-chat fallback is honest).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.conversation import ConversationService
from runtime.artifacts.manager import ArtifactManager
from shared.ids import new_id
from storage.db import transaction
from tests.conftest import World
from tests.helpers import insert_task
from tests.integration.test_alpha2 import ok, send

# ------------------------------------------------------------------ A3-13 corpus

NOT_STATUS = [
    "Como está o tempo no Rio?",
    "Qual o andamento da economia?",
    "Como vai funcionar esse software?",
    "Como está a sua mãe?",
    "O progresso da ciência é impressionante",
]
STATUS = [
    "status",
    "Qual o status?",
    "Como está o trabalho?",
    "Qual o andamento das tarefas?",
    "O que você está fazendo?",
    "Como vai a tarefa?",
]
NOT_MEMORY = ["Lembrete: pagar a conta amanhã", "Lembretes são úteis", "Anotações da reunião estão ótimas"]
MEMORY = [
    ("Guarde que prefiro relatórios curtos", "prefiro relatórios curtos"),
    ("Lembre-se: minha cor favorita é azul", "minha cor favorita é azul"),
    ("Guarde esta informação: o CEP do escritório é 01000-000", "o CEP do escritório é 01000-000"),
    ("Anote que a reunião é às 15h", "a reunião é às 15h"),
]


@pytest.mark.parametrize("text", NOT_STATUS)
def test_general_questions_are_not_task_status(env: Any, text: str) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    assert send(c, env, conv, text)["intent"] != "status"


@pytest.mark.parametrize("text", STATUS)
def test_real_status_questions_are_status(env: Any, text: str) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    assert send(c, env, conv, text)["intent"] == "status"


@pytest.mark.parametrize("text", NOT_MEMORY)
def test_reminder_words_are_not_memory_requests(env: Any, text: str) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    assert send(c, env, conv, text)["intent"] != "memory"


@pytest.mark.parametrize(("text", "stored"), MEMORY)
def test_memory_keeps_the_owner_text_exactly(env: Any, world: World, text: str, stored: str) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(c, env, conv, text)
    assert out["intent"] == "memory"
    content = world.conn.execute(
        "SELECT v.content FROM memory_versions v WHERE v.memory_id = ?", (out["memory_id"],)
    ).fetchone()[0]
    assert content == stored  # original accents kept, prefix removed exactly


# ------------------------------------------------------------------ A3-14 pending questions


def _waiting_task(env: Any, world: World, conv: str, question: str, objective: str) -> tuple[str, str]:
    with transaction(world.conn):
        tid = insert_task(world.conn, world.owner_id, world.employee.id, state="WAITING_USER")
        world.conn.execute(
            "UPDATE tasks SET conversation_id = ?, objective = ? WHERE id = ?", (conv, objective, tid)
        )
    q = ConversationService(world.conn, world.clock, env.make().broker, None).notify(
        tid, "question", question
    )
    assert q is not None
    return tid, q["message_id"]


def test_status_and_new_subject_do_not_answer_the_pending_question(env: Any, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    tid, _ = _waiting_task(
        env, world, conv, "Qual formato você prefere: PDF ou planilha?", "Relatorio de vendas"
    )
    assert send(c, env, conv, "Qual o status?")["intent"] == "status"  # before the fix: consumed as answer
    new = send(
        c, env, conv, "Me ajude a escrever um convite de aniversário para sábado, por favor, com tom leve."
    )
    assert new["intent"] != "answer"
    assert world.conn.execute("SELECT state FROM tasks WHERE id = ?", (tid,)).fetchone()[0] == "WAITING_USER"
    short = send(c, env, conv, "Planilha")  # an unambiguous continuation is still linked
    assert short["intent"] == "answer" and short["task_id"] == tid


def test_two_pending_questions_are_never_guessed(env: Any, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    t1, _ = _waiting_task(env, world, conv, "Qual formato: PDF ou planilha?", "Relatorio de vendas")
    t2, q2 = _waiting_task(env, world, conv, "Qual o prazo máximo?", "Cotacao de frete")
    out = send(c, env, conv, "Sexta-feira")
    assert out["intent"] == "answer_ambiguous" and out["task_id"] is None
    assert "Relatorio de vendas" in out["reply"]["content"] and "Cotacao de frete" in out["reply"]["content"]
    # explicit target, out of order: only the right task resumes
    out = send(c, env, conv, "Sexta-feira", reply_to_message_id=q2)
    assert out["intent"] == "answer" and out["task_id"] == t2
    states = dict(world.conn.execute("SELECT id, state FROM tasks").fetchall())
    assert states[t2] == "READY" and states[t1] == "WAITING_USER"
    again = send(c, env, conv, "Sábado", reply_to_message_id=q2)  # the question is already answered
    assert again["intent"] == "answer_rejected" and "já" in again["reply"]["content"]


# ------------------------------------------------------------------ A3-15 attachments


def _file(env: Any, world: World, tmp_path: Path, name: str = "planilha.csv") -> str:
    f = tmp_path / name
    f.write_text("item;valor\nA;10\n", encoding="utf-8")
    return (
        ArtifactManager(world.conn, world.clock, env.store_root)
        .import_file(f, actor=world.owner, employee_id=world.employee.id)
        .id
    )


def test_store_complement_and_analyze_are_different(env: Any, world: World, tmp_path: Path) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    # 1) just keep it: no task
    a1 = _file(env, world, tmp_path, "a.csv")
    kept = send(c, env, conv, "Guarde este arquivo para depois", artifact_ids=[a1])
    assert (
        kept["task_id"] is None and kept["intent"] == "share_only"
    )  # before the fix the app forced delegate
    assert world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    linked = world.conn.execute(
        "SELECT COUNT(*) FROM message_attachments WHERE artifact_id = ?", (a1,)
    ).fetchone()[0]
    assert linked == 1
    # 2) complement of an open task: attached to it, no new task
    with transaction(world.conn):
        tid = insert_task(world.conn, world.owner_id, world.employee.id, state="READY")
        world.conn.execute("UPDATE tasks SET conversation_id = ? WHERE id = ?", (conv, tid))
    a2 = _file(env, world, tmp_path, "b.csv")
    comp = send(c, env, conv, "Esse é o arquivo que faltava", artifact_ids=[a2], task_id=tid)
    assert comp["intent"] == "attach_to_task" and comp["task_id"] == tid
    assert world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert (
        world.conn.execute(
            "SELECT relation FROM artifact_links WHERE artifact_id = ? AND task_id = ?", (a2, tid)
        ).fetchone()[0]
        == "input"
    )
    rev = world.conn.execute(
        "SELECT kind FROM task_instruction_versions WHERE task_id = ? ORDER BY revision DESC", (tid,)
    ).fetchone()[0]
    assert rev == "ATTACHMENT"
    # 3) new analysis: explicit delegation creates a task with the input
    a3 = _file(env, world, tmp_path, "c.csv")
    new = send(c, env, conv, "Analise esta planilha", artifact_ids=[a3], intent="delegate")
    assert new["intent"] == "delegate" and new["task_id"] not in (None, tid)
    assert world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2


def test_attachment_with_plain_chat_is_not_a_task(env: Any, world: World, tmp_path: Path) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    a1 = _file(env, world, tmp_path)
    out = send(c, env, conv, "Olha que interessante", artifact_ids=[a1], client_message_id=new_id())
    assert out["task_id"] is None
    assert world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
