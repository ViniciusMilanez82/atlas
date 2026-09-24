from __future__ import annotations

from dataclasses import dataclass

import pytest

from runtime.tasks.engine import Lease, TaskEngine
from runtime.tasks.state_machine import TaskState
from runtime.tools.registry import ToolRegistry
from security.broker.broker import Broker
from security.budget.budget import BudgetLimits, BudgetManager
from security.policy.engine import PolicyEngine
from shared.actors import Actor
from shared.ids import new_id
from tests.conftest import World
from tests.fakes.adapters import EMAIL_SEND, OWNER_SEND, PAID_SEARCH, PURCHASE, WORKSPACE_WRITE, FakeWorld

OWNER_CHANNEL = "owner-verified-channel"


@dataclass
class ControlPlane:
    world: World
    broker: Broker
    tasks: TaskEngine
    registry: ToolRegistry
    fake: FakeWorld

    def ready_task(
        self, *, external_writes: bool = True, purchases: bool = False, data_policy: str = "INTERNAL"
    ) -> str:
        w = self.world
        tid = self.tasks.create(
            w.owner,
            employee_id=w.employee.id,
            objective="tarefa sintetica",
            external_writes=external_writes,
            purchases=purchases,
            data_policy=data_policy,
        )
        for to in (TaskState.UNDERSTANDING, TaskState.PLANNING, TaskState.READY):
            self.tasks.transition(
                tid,
                to,
                expected_version=self.tasks.get(tid)["version"],
                actor=Actor("runtime", "rt"),
                reason="test",
            )
        return tid

    def lease(self, task_id: str, worker: str = "w1") -> Lease:
        return self.tasks.acquire_lease(task_id, worker)

    @staticmethod
    def proposal(task_id: str, tool: str, tool_input: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "task_id": task_id,
            "step_id": new_id(),
            "tool_id": tool,
            "tool_version": "1.0.0",
            "input": tool_input,
            "expected_outcome": "efeito sintetico",
            "verification": {"kind": "provider_receipt", "required": True},
            "instruction_revision": 1,
        }


@pytest.fixture
def limits() -> BudgetLimits:
    return BudgetLimits("USD", monthly_limit_minor=10_000, per_task_limit_minor=5_000)


@pytest.fixture
def cp(world: World, limits: BudgetLimits) -> ControlPlane:
    registry = ToolRegistry(world.conn, world.clock)
    fake = FakeWorld()
    for manifest, kind in (
        (OWNER_SEND, "owner"),
        (EMAIL_SEND, "email"),
        (PURCHASE, "purchase"),
        (PAID_SEARCH, "search"),
        (WORKSPACE_WRITE, "workspace"),
    ):
        registry.register(manifest, fake.adapter(kind))
        registry.enable(
            manifest.tool_id, manifest.version, actor=world.owner, validation_evidence="unit tests"
        )
    broker = Broker(
        world.conn,
        world.clock,
        registry=registry,
        policy=PolicyEngine(),
        budget=BudgetManager(world.conn, world.clock, limits),
        owner_channels=frozenset({OWNER_CHANNEL}),
    )
    return ControlPlane(world, broker, broker.tasks, registry, fake)
