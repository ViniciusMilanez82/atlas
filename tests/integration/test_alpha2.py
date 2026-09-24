"""Alpha 2 corrections (review 2a7fd85) exercised over the real IPC protocol.

A1 settings revisions, A2 bidirectional conversation, A4 attachments, A8 intelligence check in the
global ledger. Model behaviour comes from a CONTROLLED LOCAL HTTP SERVER (no network, no cost):
this proves routing and bookkeeping, not the quality of any real model.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.conversation import ConversationService
from core.intelligence import IntelligenceSetup
from core.ipc.server import serve_connection
from core.ipc.sessions import SessionRegistry
from core.service import CoreService
from runtime.artifacts.manager import ArtifactManager
from runtime.tools.registry import ToolRegistry
from security.broker.broker import Broker
from security.budget.budget import BudgetLimits, BudgetManager
from security.policy.engine import PolicyEngine
from security.vault.vault import Vault
from shared.actors import Actor
from shared.ids import new_id
from storage.db import transaction
from storage.store import open_store
from tests.conftest import World
from tests.fakes.vault_backend import FakeInMemoryVaultBackend
from tests.helpers import insert_task
from tests.integration.test_ipc import Client, err
from tests.integration.test_openai_adapter import FakeOpenAI, ok_body

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "sk-proj-" + "A" * 40  # atlas-scan: allow-fake-secret


def base_config(**budget: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = yaml.safe_load((ROOT / "config" / "atlas.default.yaml").read_text(encoding="utf-8"))
    cfg["budget"]["monthly_limit_minor"] = 500
    cfg["budget"]["per_task_limit_minor"] = 40
    cfg["budget"].update(budget)
    return cfg


class Env:
    def __init__(self, world: World, tmp_path: Path, base_url: str) -> None:
        self.world = world
        self.sessions = SessionRegistry()
        self.backend = FakeInMemoryVaultBackend()
        self.base_url = base_url
        self.store_root = tmp_path / "artifacts"
        self.opened: list[socket.socket] = []

    def make(self) -> CoreService:
        w = self.world
        conn = open_store(w.path, w.clock)
        broker = Broker(
            conn,
            w.clock,
            registry=ToolRegistry(conn, w.clock),
            policy=PolicyEngine(),
            budget=BudgetManager(conn, w.clock, BudgetLimits("USD", None, None)),
        )
        intel = IntelligenceSetup(conn, w.clock, Vault(conn, self.backend, w.clock), base_url=self.base_url)
        return CoreService(
            conn,
            w.clock,
            broker,
            intelligence=intel,
            artifacts=ArtifactManager(conn, w.clock, self.store_root),
        )

    def connect(self, actor: Actor | None = None, employee_id: str | None = None) -> Client:
        a, b = socket.socketpair()
        self.opened.append(a)
        threading.Thread(target=serve_connection, args=(b, self.sessions, self.make), daemon=True).start()
        client = Client(a)
        token = self.sessions.issue(actor or self.world.owner, employee_id or self.world.employee.id)
        assert client.hello(token)["hello"] == "ok"
        return client


@pytest.fixture
def api() -> Iterator[FakeOpenAI]:
    fake = FakeOpenAI()
    yield fake
    fake.close()


@pytest.fixture
def env(world: World, tmp_path: Path, api: FakeOpenAI) -> Iterator[Env]:
    e = Env(world, tmp_path, api.url)
    yield e
    for s in e.opened:
        s.close()


def ok(resp: dict[str, Any]) -> dict[str, Any]:
    assert "result" in resp, resp
    return resp["result"]  # type: ignore[no-any-return]


def save(c: Client, cfg: dict[str, Any]) -> dict[str, Any]:
    rev = ok(c.call("settings.get"))["revision"]
    return c.call("settings.update", expected_revision=rev, settings=cfg)


def send(c: Client, env: Env, conv: str, text: str, **kw: Any) -> dict[str, Any]:
    kw.setdefault("client_message_id", new_id())
    return ok(
        c.call(
            "conversations.send",
            employee_id=env.world.employee.id,
            conversation_id=conv,
            text=text,
            **kw,
        )
    )


def configure_intelligence(c: Client, api: FakeOpenAI) -> None:
    ok(
        c.call(
            "credentials.register", provider="openai", secret_b64=base64.b64encode(FAKE_KEY.encode()).decode()
        )
    )
    ok(save(c, base_config(accept_reference_prices=True)))
    api.queue.append((200, {}, {"id": "gpt-6-sol", "object": "model"}))
    api.queue.append((200, {}, ok_body(text='{"ok": true, "word": "atlas"}')))
    report = ok(c.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=5))["report"]
    assert report["passed"] is True, report


# ---------------------------------------------------------------------------------------- 1A settings


def test_three_sequential_saves_reopen_and_values_preserved(env: Env) -> None:
    c = env.connect()
    assert ok(c.call("settings.get"))["revision"] == 0
    for i, limit in enumerate((300, 400, 500), start=1):
        assert ok(save(c, base_config(monthly_limit_minor=limit)))["revision"] == i
    c2 = env.connect()  # "close and reopen the app": a fresh session reads what was saved
    got = ok(c2.call("settings.get"))
    assert got["revision"] == 3 and got["settings"]["budget"]["monthly_limit_minor"] == 500
    assert got["prices_verified"] is False and got["price_table"]
    assert ok(c2.call("identity.get"))["settings_revision"] == 3


def test_concurrent_clients_one_wins_other_recovers(env: Env) -> None:
    c1, c2 = env.connect(), env.connect()
    ok(save(c1, base_config()))
    rev = ok(c1.call("settings.get"))["revision"]
    barrier = threading.Barrier(2)
    results: dict[str, dict[str, Any]] = {}

    def attempt(name: str, c: Client, limit: int) -> None:
        barrier.wait()
        results[name] = c.call(
            "settings.update", expected_revision=rev, settings=base_config(monthly_limit_minor=limit)
        )

    t = [threading.Thread(target=attempt, args=(n, c, v)) for n, c, v in (("a", c1, 111), ("b", c2, 222))]
    for th in t:
        th.start()
    for th in t:
        th.join()
    winners = [n for n, r in results.items() if "result" in r]
    losers = [n for n, r in results.items() if "error" in r]
    assert len(winners) == 1 and len(losers) == 1
    assert err(results[losers[0]]) == "VERSION_CONFLICT"
    loser_client = c1 if losers[0] == "a" else c2
    assert (
        ok(save(loser_client, base_config(monthly_limit_minor=333)))["revision"] == rev + 2
    )  # reload + retry
    assert ok(c1.call("settings.get"))["settings"]["budget"]["monthly_limit_minor"] == 333


def test_invalid_settings_error_is_recoverable(env: Env) -> None:
    c = env.connect()
    ok(save(c, base_config()))
    bad = base_config()
    bad["security"]["host_shell_enabled"] = True  # pinned safe value
    assert err(save(c, bad)) == "INVALID_INPUT"
    assert ok(c.call("settings.get"))["revision"] == 1  # nothing half-written
    assert ok(save(c, base_config(monthly_limit_minor=42)))["revision"] == 2


# ---------------------------------------------------------------------------------------- 2A conversation


def test_greeting_creates_no_task_and_reply_is_honest(env: Env) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    assert ok(c.call("conversations.current"))["conversation_id"] == conv  # persistent id
    out = send(c, env, conv, "Oi, tudo bem?")
    assert out["task_id"] is None and out["intent"] == "chat_unavailable"
    assert "Delegar como tarefa" in out["reply"]["content"]
    assert env.world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_explicit_delegation_links_task_to_conversation_idempotently(env: Env) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    mid = new_id()
    out = send(c, env, conv, "Compare as duas propostas", intent="delegate", client_message_id=mid)
    again = send(c, env, conv, "Compare as duas propostas", intent="delegate", client_message_id=mid)
    assert again["duplicate"] is True and again["task_id"] == out["task_id"]
    task = ok(c.call("tasks.get", task_id=out["task_id"]))["task"]
    assert task["objective"] == "Compare as duas propostas"
    row = env.world.conn.execute(
        "SELECT conversation_id FROM tasks WHERE id = ?", (out["task_id"],)
    ).fetchone()
    assert row[0] == conv
    assert out["reply"]["kind"] == "ack" and out["reply"]["task_id"] == out["task_id"]
    assert env.world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_delegate_an_earlier_message_after_honest_refusal(env: Env) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    first = send(c, env, conv, "Faça um resumo do contrato")
    assert first["task_id"] is None
    out = send(c, env, conv, "delegar", intent="delegate", reply_to_message_id=first["message_id"])
    assert out["task_id"] and ok(c.call("tasks.get", task_id=out["task_id"]))["task"]["objective"] == (
        "Faça um resumo do contrato"
    )
    owner_msgs = env.world.conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'owner'").fetchone()[0]
    assert owner_msgs == 1  # delegation does not invent a second owner message


def test_question_answer_resumes_waiting_task(env: Env, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    with transaction(world.conn):
        tid = insert_task(world.conn, world.owner_id, world.employee.id, state="WAITING_USER")
        world.conn.execute("UPDATE tasks SET conversation_id = ? WHERE id = ?", (conv, tid))
    svc = ConversationService(world.conn, world.clock, env.make().broker, None)
    q = svc.notify(tid, "question", "Qual formato você prefere: PDF ou planilha?")
    assert q is not None and q["task_id"] == tid
    out = send(c, env, conv, "Planilha")
    assert out["intent"] == "answer" and out["task_id"] == tid
    assert ok(c.call("tasks.get", task_id=tid))["task"]["state"] == "READY"
    kinds = [m["kind"] for m in ok(c.call("conversations.history", conversation_id=conv))["messages"]]
    assert kinds == ["question", "answer", "ack"]


def test_status_query_is_built_from_the_database(env: Env, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    with transaction(world.conn):
        tid = insert_task(world.conn, world.owner_id, world.employee.id, state="READY")
        world.conn.execute(
            "UPDATE tasks SET state = 'BLOCKED', blocked_reason = 'HUMAN_INTERVENTION_REQUIRED' WHERE id = ?",
            (tid,),
        )
    out = send(c, env, conv, "Qual o status?")
    assert out["intent"] == "status" and "bloqueada (precisa de você)" in out["reply"]["content"]
    assert out["task_id"] is None


def test_memory_request_needs_confirmation(env: Env) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(c, env, conv, "Guarde que prefiro relatórios curtos")
    assert out["intent"] == "memory" and out["reply"]["memory_id"] == out["memory_id"]
    hits = ok(c.call("memories.search", employee_id=env.world.employee.id, query="relatórios curtos"))["hits"]
    assert hits == []  # proposed only: not used until confirmed
    ok(c.call("memories.confirm", memory_id=out["memory_id"]))
    hits = ok(c.call("memories.search", employee_id=env.world.employee.id, query="relatórios curtos"))["hits"]
    assert [h["memory_id"] for h in hits] == [out["memory_id"]]
    device = env.connect(Actor("device", "phone-1", "paired_device"))
    assert err(device.call("memories.confirm", memory_id=out["memory_id"])) == "UNAUTHORIZED"


def test_correction_attaches_to_open_task(env: Env) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    task = send(c, env, conv, "Liste fornecedores de papel", intent="delegate")["task_id"]
    out = send(c, env, conv, "Na verdade, só fornecedores do Rio")
    assert out["intent"] == "correction" and out["task_id"] == task
    assert env.world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_history_pagination_and_isolation(env: Env, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    for i in range(5):
        send(c, env, conv, f"mensagem {i}")  # each gets an honest reply -> 10 messages
    page1 = ok(c.call("conversations.history", conversation_id=conv, limit=4))
    assert page1["has_more"] is True and len(page1["messages"]) == 4
    page2 = ok(
        c.call(
            "conversations.history",
            conversation_id=conv,
            limit=10,
            before_message_id=page1["messages"][0]["message_id"],
        )
    )
    assert page2["has_more"] is False and len(page2["messages"]) == 6
    all_ids = [m["message_id"] for m in page2["messages"] + page1["messages"]]
    assert len(set(all_ids)) == 10
    from storage.repositories.identity import create_employee

    other = create_employee(world.conn, world.clock, owner_id=world.owner_id, name="Outro")
    c_other = env.connect(employee_id=other.id)
    assert err(c_other.call("conversations.history", conversation_id=conv)) == "UNAUTHORIZED"


def test_chat_with_model_replies_without_task_and_ledger_is_employee_scoped(
    env: Env, api: FakeOpenAI
) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    api.queue.append(
        (200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "Olá! Tudo bem.", "objective": ""})))
    )
    out = send(c, env, conv, "Oi!")
    assert out["intent"] == "chat" and out["reply"]["content"] == "Olá! Tudo bem." and out["task_id"] is None
    api.queue.append(
        (
            200,
            {},
            ok_body(
                text=json.dumps(
                    {"intent": "delegate", "reply": "", "objective": "Pesquisar preços de papel A4"}
                )
            ),
        )
    )
    out = send(c, env, conv, "Você pode pesquisar preços de papel A4 pra mim?")
    assert out["intent"] == "delegate" and out["task_id"]
    rows = env.world.conn.execute(
        "SELECT purpose, task_id, employee_id, status FROM inference_attempts ORDER BY created_at, rowid"
    ).fetchall()
    assert [(r[0], r[1], r[3]) for r in rows] == [
        ("intelligence_check", None, "SETTLED"),
        ("conversation", None, "SETTLED"),
        ("conversation", None, "SETTLED"),
    ]
    assert all(r[2] == env.world.employee.id for r in rows)
    assert FAKE_KEY not in json.dumps(out)


def test_model_failure_is_reported_and_nothing_executes(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    api.queue.append((200, {}, ok_body(text="isto não é json")))
    out = send(c, env, conv, "Oi")
    assert out["intent"] == "chat_error" and out["task_id"] is None
    assert env.world.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


# ---------------------------------------------------------------------------------------- 3D check


def test_unverified_prices_block_check_until_accepted(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    ok(
        c.call(
            "credentials.register", provider="openai", secret_b64=base64.b64encode(FAKE_KEY.encode()).decode()
        )
    )
    ok(save(c, base_config()))  # ceilings set but reference prices NOT accepted
    resp = c.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=5)
    assert err(resp) == "MODEL_UNSUPPORTED" and "not verified" in resp["error"]["message"]
    assert api.requests == []  # not even the free metadata call
    health = ok(c.call("system.health"))
    assert health["components"]["intelligence"] == "not_configured"


def test_check_respects_monthly_ceiling_of_global_ledger(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    ok(
        c.call(
            "credentials.register", provider="openai", secret_b64=base64.b64encode(FAKE_KEY.encode()).decode()
        )
    )
    ok(save(c, base_config(monthly_limit_minor=40, accept_reference_prices=True)))
    from security.budget.budget import BudgetLimits, BudgetManager
    from shared.money import Money

    budget = BudgetManager(env.world.conn, env.world.clock, BudgetLimits("USD", 40, 40))
    with transaction(env.world.conn):  # an earlier synthetic spend already used the monthly ceiling
        res = budget.reserve_in_txn(task_id=None, category="inference", amount=Money(40, "USD"))
        budget.settle_in_txn(res.id, Money(40, "USD"))
    api.queue.append((200, {}, {"id": "gpt-6-sol", "object": "model"}))
    report = ok(c.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=5))["report"]
    assert report["passed"] is False and any(e.startswith("budget:") for e in report["errors"])
    assert [r["path"] for r in api.requests] == ["/v1/models/gpt-6-sol"]  # no billable call


def test_concurrent_checks_run_one_at_a_time(env: Env, api: FakeOpenAI) -> None:
    c1, c2 = env.connect(), env.connect()
    ok(
        c1.call(
            "credentials.register", provider="openai", secret_b64=base64.b64encode(FAKE_KEY.encode()).decode()
        )
    )
    ok(save(c1, base_config(accept_reference_prices=True)))
    api.queue.append((200, {}, "hang"))  # first check stalls on the metadata call
    api.queue.append((200, {}, ok_body(text='{"ok": true, "word": "atlas"}')))
    results: list[dict[str, Any]] = []
    t = threading.Thread(
        target=lambda: results.append(c1.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=5))
    )
    t.start()
    import time

    deadline = time.monotonic() + 2
    while not api.requests and time.monotonic() < deadline:
        time.sleep(0.02)
    second = c2.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=5)
    assert err(second) == "VERSION_CONFLICT"
    t.join(10)
    assert results and "result" in results[0]


# ---------------------------------------------------------------------------------------- 2B attachments


def upload(c: Client, employee_id: str, data: bytes, name: str, chunk: int = 7) -> dict[str, Any]:
    ref = new_id()
    for off in range(0, len(data), chunk):
        part = base64.b64encode(data[off : off + chunk]).decode()
        ok(c.call("artifacts.upload", upload_ref=ref, offset=off, data_b64=part))
    return c.call("artifacts.import", employee_id=employee_id, upload_ref=ref, declared_name=name)


def test_two_attachments_to_task_and_read_back_with_hash(env: Env) -> None:
    c = env.connect()
    a = ok(upload(c, env.world.employee.id, b"fornecedor,preco\nA,10\nB,12\n", "proposta_a.csv"))
    b = ok(
        upload(c, env.world.employee.id, "# Proposta B\nPreço total: R$ 1.200,00\n".encode(), "proposta_b.md")
    )
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(
        c,
        env,
        conv,
        "Compare as duas propostas e gere um relatório",
        intent="delegate",
        artifact_ids=[a["artifact_id"], b["artifact_id"]],
    )
    listed = ok(c.call("artifacts.list", task_id=out["task_id"]))["artifacts"]
    assert sorted((x["name"], x["relation"]) for x in listed) == [
        ("proposta_a.csv", "input"),
        ("proposta_b.md", "input"),
    ]
    got, off = b"", 0
    while True:
        r = ok(c.call("artifacts.read", artifact_id=b["artifact_id"], offset=off, length=5))
        piece = base64.b64decode(r["data_b64"])
        assert hashlib.sha256(piece).hexdigest() == r["chunk_sha256"]
        got += piece
        off += len(piece)
        if r["eof"]:
            break
    assert hashlib.sha256(got).hexdigest() == b["sha256"] == r["sha256"]
    assert not list((env.store_root / "uploads").iterdir())  # staging copies are removed


def test_upload_resend_conflict_and_validation(env: Env, world: World) -> None:
    c = env.connect()
    ref = new_id()
    first = base64.b64encode(b"hello ").decode()
    assert ok(c.call("artifacts.upload", upload_ref=ref, offset=0, data_b64=first))["received_bytes"] == 6
    assert ok(c.call("artifacts.upload", upload_ref=ref, offset=0, data_b64=first))["duplicate"] is True
    other = base64.b64encode(b"HELLO!").decode()
    assert err(c.call("artifacts.upload", upload_ref=ref, offset=0, data_b64=other)) == "VERSION_CONFLICT"
    assert err(c.call("artifacts.upload", upload_ref=ref, offset=99, data_b64=other)) == "VERSION_CONFLICT"
    # content that does not match the extension is rejected, and the staging file is still removed
    assert err(upload(c, env.world.employee.id, b"%PDF-1.7 fake", "nota.txt")) == "INVALID_INPUT"
    assert err(upload(c, env.world.employee.id, b"plain text", "virus.exe")) == "INVALID_INPUT"
    bad = c.call(
        "artifacts.import", employee_id=world.employee.id, upload_ref=new_id(), declared_name="../x.txt"
    )
    assert err(bad) == "INVALID_INPUT"


def test_attachments_are_owner_local_and_employee_scoped(env: Env, world: World) -> None:
    c = env.connect()
    art = ok(upload(c, env.world.employee.id, b"dados sinteticos", "dados.txt"))
    device = env.connect(Actor("device", "phone-1", "paired_device"))
    assert err(device.call("artifacts.upload", upload_ref=new_id(), offset=0, data_b64="")) == "UNAUTHORIZED"
    from storage.repositories.identity import create_employee

    other = create_employee(world.conn, world.clock, owner_id=world.owner_id, name="Outro")
    c_other = env.connect(employee_id=other.id)
    assert (
        err(c_other.call("artifacts.read", artifact_id=art["artifact_id"], offset=0, length=10))
        == "INVALID_INPUT"
    )
    conv = ok(c_other.call("conversations.current"))["conversation_id"]
    resp = c_other.call(
        "conversations.send",
        employee_id=other.id,
        conversation_id=conv,
        client_message_id=new_id(),
        text="use o anexo",
        intent="delegate",
        artifact_ids=[art["artifact_id"]],
    )
    assert err(resp) == "INVALID_INPUT"
