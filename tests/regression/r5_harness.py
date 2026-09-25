"""In-process world for the R5 regressions (review of PR #5, docs/REVIEW_PR5_REMEDIATION.md).

Real SQLite + migrations, TaskEngine, ConversationService, AgentRunner, Broker, Verifier, the real
BudgetedModelClient and the real EgressGuard. Only the provider is replaced by a local recorder that
keeps every request it received, so the tests assert on the bytes that would have left the machine.
No network, no credentials; every secret is a synthetic sentinel.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.conversation import ConversationService
from runtime.agent.loop import AgentRunner
from runtime.artifacts.manager import Artifact, ArtifactManager
from runtime.memory.manager import MemoryManager
from runtime.models.pricing import SPEC_REFERENCE_TABLE
from runtime.models.router import BudgetedModelClient, CatalogEntry, Consent, ModelRouter
from runtime.models.types import ModelCapabilities, ModelRequest, ModelResponse, Usage
from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from runtime.tools.builtin import BUILTIN_MANIFESTS, BuiltinTools
from runtime.tools.registry import ToolRegistry
from runtime.verification.criteria import derive_criteria
from runtime.verification.verifier import Verifier
from security.broker.broker import Broker
from security.budget.budget import BudgetLimits, BudgetManager
from security.egress.guard import EgressGuard
from security.policy.engine import PolicyEngine
from shared.actors import Actor
from shared.clock import ManualClock
from shared.ids import new_id
from storage.db import transaction
from storage.repositories.identity import create_employee, create_owner
from storage.store import open_store
from tests.integration.test_alpha2 import base_config

CP = Actor("control_plane", "broker", "internal")
MODEL = "gpt-6-sol"  # fixture identifier only


def decision(kind: str = "ask_owner", **kw: Any) -> dict[str, Any]:
    data = {
        "decision": kind,
        "summary": "synthetic decision",
        "tool_id": "",
        "input_json": "{}",
        "artifact_id": "",
        "question": "Qual resultado deseja?",
        "capability_json": "{}",
    }
    data.update(kw)
    return data


class RecordingProvider:
    provider_id = "openai"

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []
        self.reply: dict[str, Any] | Callable[[ModelRequest], dict[str, Any]] = decision()
        self.hook: Callable[[ModelRequest], None] | None = None

    def capabilities(self, _: str) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True)

    def estimate_usage(self, r: ModelRequest) -> Usage:
        return Usage(100, 0, r.max_output_tokens)

    def generate(self, r: ModelRequest) -> ModelResponse:
        self.calls.append(r)
        if self.hook is not None:
            self.hook(r)
        reply = self.reply(r) if callable(self.reply) else self.reply
        return ModelResponse("openai", MODEL, f"local-{len(self.calls)}", json.dumps(reply), usage=Usage(100, 0, 100))

    def sent(self) -> str:
        """Everything that reached the provider, concatenated (what would have left the machine)."""
        return "\n".join(m.content for r in self.calls for m in r.messages)


class R5World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = ManualClock()
        self.conn = open_store(root / "atlas.sqlite", self.clock)
        self.owner_id = create_owner(self.conn, self.clock, "Synthetic owner")
        self.emp = create_employee(self.conn, self.clock, owner_id=self.owner_id, name="Atlas synthetic")
        self.owner = Actor("owner", self.owner_id, "local_app", strong_auth=True)
        self.tasks = TaskEngine(self.conn, self.clock)
        self.artifacts = ArtifactManager(self.conn, self.clock, root / "artifacts")
        reg = ToolRegistry(self.conn, self.clock)
        BuiltinTools(root / "atlas.sqlite", root / "artifacts", self.clock).register(
            reg, enabled_by=Actor("supervisor", "test", "internal")
        )
        self.budget = BudgetManager(self.conn, self.clock, BudgetLimits("USD", 1_000_000, 100_000))
        self.broker = Broker(self.conn, self.clock, registry=reg, policy=PolicyEngine(), budget=self.budget)
        self.provider = RecordingProvider()
        self.client = BudgetedModelClient(
            self.conn,
            self.clock,
            ModelRouter(
                [CatalogEntry("openai", MODEL, "general", 1, ModelCapabilities(structured_output=True), validated=True)],
                Consent({"openai"}, sensitive_data_providers={"openai"}),  # as core/intelligence builds it
            ),
            {"openai": self.provider},
            SPEC_REFERENCE_TABLE,
            self.budget,
            egress=EgressGuard(self.conn),
        )
        self.intel = SimpleNamespace(status=lambda: SimpleNamespace(configured=True), build_client=lambda: self.client)
        self.conv = ConversationService(self.conn, self.clock, self.broker, self.intel)  # type: ignore[arg-type]
        self.cid = self.conv.current(self.emp.id)
        self.memory = MemoryManager(self.conn, self.clock)
        self.verifier = Verifier(self.conn, self.clock, self.artifacts)
        self.runner = AgentRunner(
            self.conn,
            self.clock,
            broker=self.broker,
            model=self.client,
            memory=self.memory,
            verifier=self.verifier,
            tools=[m.tool_id for m in BUILTIN_MANIFESTS],
        )

    # ------------------------------------------------------------------ helpers

    def consent(self, *consents: dict[str, Any]) -> None:
        cfg = base_config(monthly_limit_minor=100_000, per_task_limit_minor=50_000)
        cfg["privacy"] = {"sensitive_consents": list(consents)}
        with transaction(self.conn):
            rev = self.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM settings").fetchone()[0]
            self.conn.execute(
                "INSERT INTO settings(revision, config_json, updated_at, updated_by) VALUES (?,?,?,?)",
                (rev + 1, json.dumps(cfg), "2026-01-01T00:00:00.000Z", "owner:test"),
            )

    def send(self, text: str, **kw: Any) -> dict[str, Any]:
        p: dict[str, Any] = {"conversation_id": self.cid, "client_message_id": new_id(), "text": text}
        p.update(kw)
        return self.conv.handle(self.owner, self.emp.id, p)

    def create(self, objective: str, has_inputs: bool = False, **kw: Any) -> str:
        return self.tasks.create(
            self.owner,
            employee_id=self.emp.id,
            objective=objective,
            conversation_id=self.cid,
            criteria=[(c.description, c.required, c.kind, c.params) for c in derive_criteria(objective, has_inputs)],
            **kw,
        )

    def artifact(self, task_id: str, text: str, name: str = "relatorio.txt") -> Artifact:
        return self.artifacts.create_text(actor=CP, employee_id=self.emp.id, task_id=task_id, name=name, content=text)

    def import_text(self, text: str, name: str = "proposta.txt", task_id: str | None = None) -> Artifact:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return self.artifacts.import_file(path, actor=self.owner, employee_id=self.emp.id, task_id=task_id)

    def waiting_question(self, task_id: str, text: str = "Qual informação falta?") -> dict[str, Any]:
        """Put the task in WAITING_USER with a question delivered through the outbox (the real path)."""
        self.runner._prepare(task_id)
        lease = self.tasks.acquire_lease(task_id, "test-worker")
        self.tasks.release(lease, TaskState.WAITING_USER, "synthetic question", notice=("question", text, None))
        self.runner._deliver(task_id)
        row = self.conn.execute(
            "SELECT id FROM messages WHERE task_id = ? AND kind = 'question' ORDER BY rowid DESC LIMIT 1", (task_id,)
        ).fetchone()
        return self.conv.get_message(row[0])

    def state(self, task_id: str) -> str:
        return str(self.tasks.get(task_id)["state"])

    def close(self) -> None:
        self.conn.close()


@pytest.fixture
def r5(tmp_path: Path) -> Iterator[R5World]:
    w = R5World(tmp_path)
    yield w
    w.close()
