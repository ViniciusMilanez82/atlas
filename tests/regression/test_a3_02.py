"""A3-02 / T08: sensitive content keeps its classification until the final payload; without a scoped
consent no request to the provider contains a sensitive sentinel.

Synthetic sentinels in memory, attachment and conversation. Every request that reached the CONTROLLED
local model server (or the scripted fake model) is inspected, not just the reply.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from runtime.agent.loop import AgentRunner
from runtime.artifacts.manager import ArtifactManager
from runtime.memory.manager import MemoryManager
from runtime.models.pricing import SPEC_REFERENCE_TABLE
from runtime.models.router import BudgetedModelClient, CatalogEntry, Consent, ModelRouter
from runtime.models.types import ModelCapabilities
from runtime.tools.builtin import BuiltinTools
from runtime.tools.registry import ToolRegistry
from runtime.verification.verifier import Verifier
from security.broker.broker import Broker
from security.budget.budget import BudgetManager
from security.egress.guard import EgressGuard
from security.policy.engine import PolicyEngine
from shared.ids import new_id
from storage.db import transaction
from tests.conftest import World
from tests.integration.test_agent_loop import SPEC, UUID, ScriptedModel, decision
from tests.integration.test_alpha2 import base_config, configure_intelligence, ok, save, send
from tests.integration.test_openai_adapter import ok_body

SENTINEL_MEMORY = "SENTINELA-SAUDE-7741"
SENTINEL_DOC = "SENTINELA-LAUDO-9902"


def _settings(world: World, consents: list[dict[str, Any]] | None = None) -> None:
    cfg = base_config(monthly_limit_minor=100_000, per_task_limit_minor=50_000)
    if consents is not None:
        cfg["privacy"] = {"sensitive_consents": consents}
    with transaction(world.conn):
        rev = world.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM settings").fetchone()[0]
        world.conn.execute(
            "INSERT INTO settings(revision, config_json, updated_at, updated_by) VALUES (?,?,?,?)",
            (rev + 1, json.dumps(cfg), "2026-01-01T00:00:00.000Z", "owner:test"),
        )


def _stack(world: World, tmp_path: Path, policy: Any) -> tuple[AgentRunner, ScriptedModel, ArtifactManager]:
    store = tmp_path / "store"
    am = ArtifactManager(world.conn, world.clock, store)
    reg = ToolRegistry(world.conn, world.clock)
    BuiltinTools(world.path, store, world.clock).register(reg, enabled_by=world.owner)
    budget = BudgetManager.live(world.conn, world.clock)
    broker = Broker(world.conn, world.clock, registry=reg, policy=PolicyEngine(), budget=budget)
    model = ScriptedModel(policy)
    caps = ModelCapabilities(structured_output=True)
    client = BudgetedModelClient(
        world.conn,
        world.clock,
        ModelRouter(
            [CatalogEntry("openai", "gpt-6-sol", "general", 2, caps, True)],
            Consent({"openai"}, sensitive_data_providers={"openai"}),
        ),
        {"openai": model},
        SPEC_REFERENCE_TABLE,
        budget,
        egress=EgressGuard(world.conn),
    )
    runner = AgentRunner(
        world.conn,
        world.clock,
        broker=broker,
        model=client,
        memory=MemoryManager(world.conn, world.clock),
        verifier=Verifier(world.conn, world.clock, am),
        tools=["artifact.read_text", "artifact.write_text", "memory.search"],
    )
    return runner, model, am


def _sensitive_memory(world: World) -> None:
    mm = MemoryManager(world.conn, world.clock)
    src = mm.add_source(actor=world.owner, kind="owner_message", ref="conversa/sintetica")
    mm.propose(
        actor=world.owner,
        employee_id=world.employee.id,
        type="FACT",
        content=f"Relatorio medico do proprietario: {SENTINEL_MEMORY}",
        source_id=src,
        sensitivity="SENSITIVE",
    )


def test_sensitive_memory_never_reaches_the_provider_without_consent(world: World, tmp_path: Path) -> None:
    _settings(world)
    _sensitive_memory(world)
    runner, model, _ = _stack(world, tmp_path, lambda t, p: decision("ask_owner", question="Qual o formato?"))
    tid = runner.tasks.create(
        world.owner,
        employee_id=world.employee.id,
        objective="Resuma o relatorio medico",
        criteria=[("x", True)],
    )
    runner.run(tid, SPEC)
    assert model.prompts, "the task itself is not sensitive: the model is still called"
    assert all(SENTINEL_MEMORY not in p for p in model.prompts)  # before the fix: sent as VERIFIED FACT


def test_sensitive_attachment_blocks_instead_of_leaking(world: World, tmp_path: Path) -> None:
    _settings(world)

    def policy(turn: int, prompt: str) -> str:
        ids = re.findall(rf"artifact_id ({UUID})", prompt)
        return decision("tool", tool="artifact.read_text", inp={"artifact_id": ids[0]}, summary="ler laudo")

    runner, model, am = _stack(world, tmp_path, policy)
    tid = runner.tasks.create(
        world.owner, employee_id=world.employee.id, objective="Analise o anexo", criteria=[("x", True)]
    )
    f = tmp_path / "laudo.txt"
    f.write_text(f"Laudo sintetico {SENTINEL_DOC}", encoding="utf-8")
    am.import_file(
        f, actor=world.owner, employee_id=world.employee.id, task_id=tid, classification="SENSITIVE"
    )
    out = runner.run(tid, SPEC)
    assert all(SENTINEL_DOC not in p for p in model.prompts)  # before the fix: tool output sent back
    assert out.state == "WAITING_USER"
    q = world.conn.execute(
        "SELECT kind, content FROM notification_outbox WHERE task_id = ?", (tid,)
    ).fetchone()
    assert q[0] == "question" and "sensível" in q[1]


def test_scoped_consent_allows_only_its_purpose_and_revocation_is_immediate(
    world: World, tmp_path: Path
) -> None:
    _settings(world, [{"provider": "openai", "purposes": ["task"]}])

    def policy(turn: int, prompt: str) -> str:
        ids = re.findall(rf"artifact_id ({UUID})", prompt)
        if turn == 1:
            return decision(
                "tool", tool="artifact.read_text", inp={"artifact_id": ids[0]}, summary="ler laudo"
            )
        _settings(world, [{"provider": "openai", "purposes": ["conversation"]}])  # owner revokes for tasks
        return decision("ask_owner", question="ok?")

    runner, model, am = _stack(world, tmp_path, policy)
    tid = runner.tasks.create(
        world.owner, employee_id=world.employee.id, objective="Analise o anexo", criteria=[("x", True)]
    )
    f = tmp_path / "laudo.txt"
    f.write_text(f"Laudo sintetico {SENTINEL_DOC}", encoding="utf-8")
    am.import_file(
        f, actor=world.owner, employee_id=world.employee.id, task_id=tid, classification="SENSITIVE"
    )
    runner.run(tid, SPEC)
    assert any(SENTINEL_DOC in p for p in model.prompts)  # consented: the needed content was sent
    third = world.conn.execute("SELECT state FROM tasks WHERE id = ?", (tid,)).fetchone()[0]
    assert third == "WAITING_USER"
    assert len([p for p in model.prompts if SENTINEL_DOC in p]) == 1  # after revocation: not sent again


def test_conversation_echo_of_a_sensitive_memory_is_not_sent(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    out = send(c, env, conv, f"Guarde que o CPF do meu filho e {SENTINEL_MEMORY}")
    assert out["intent"] == "memory"
    api.queue.append(
        (200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "Bom dia!", "objective": ""})))
    )
    send(c, env, conv, "Bom dia")
    sent = json.dumps([r["body"] for r in api.requests if r["path"].endswith("/responses")])
    assert SENTINEL_MEMORY not in sent  # before the fix: the request and its echo went as history
    blocked = send(c, env, conv, f"Qual e o CPF {SENTINEL_MEMORY}?")
    assert blocked["intent"] == "chat_blocked_sensitive"
    sent = json.dumps([r["body"] for r in api.requests if r["path"].endswith("/responses")])
    assert SENTINEL_MEMORY not in sent


def test_consent_for_conversation_lets_the_owner_talk_about_it(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    cfg = base_config(accept_reference_prices=True)
    cfg["privacy"] = {"sensitive_consents": [{"provider": "openai", "purposes": ["conversation"]}]}
    ok(save(c, cfg))
    conv = ok(c.call("conversations.current"))["conversation_id"]
    api.queue.append(
        (200, {}, ok_body(text=json.dumps({"intent": "chat", "reply": "Anotado.", "objective": ""})))
    )
    out = send(c, env, conv, f"Meu filho tem exame amanha {SENTINEL_MEMORY}", client_message_id=new_id())
    assert out["intent"] == "chat"
    assert SENTINEL_MEMORY in json.dumps(api.requests[-1]["body"])
