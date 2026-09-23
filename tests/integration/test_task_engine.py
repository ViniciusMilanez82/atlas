"""AT-010.1..010.4 and GA-12: task engine, leases, fencing, pause, cancel, stop-all, recovery."""

from __future__ import annotations

import pytest

from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from shared.actors import Actor
from shared.contracts import validate
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.money import Money
from storage import journal
from storage.db import transaction
from tests.conftest import World
from tests.helpers import insert_action

S = TaskState


@pytest.fixture
def engine(world: World) -> TaskEngine:
    return TaskEngine(world.conn, world.clock)


def make_ready(engine: TaskEngine, world: World, **kw: object) -> str:
    tid = engine.create(world.owner, employee_id=world.employee.id, objective="Comparar propostas", **kw)  # type: ignore[arg-type]
    for to in (S.UNDERSTANDING, S.PLANNING, S.READY):
        v = engine.get(tid)["version"]
        engine.transition(tid, to, expected_version=v, actor=Actor("runtime", "rt"), reason="test")
    return tid


class TestCreation:
    def test_created_task_matches_contract(self, engine: TaskEngine, world: World) -> None:
        tid = engine.create(
            world.owner,
            employee_id=world.employee.id,
            objective="Gerar relatorio",
            criteria=[("Arquivo abre", True), ("Tem fontes", True)],
            budget_limit=Money(500, "USD"),
        )
        task = engine.get(tid)
        validate("task", task)
        assert task["state"] == "CREATED"
        assert len(task["completion_criteria"]) == 2
        events = journal.events_after(world.conn, world.employee.id, 0)
        assert events[-1]["type"] == "task.created"

    def test_only_owner_or_runtime_subtask(self, engine: TaskEngine, world: World) -> None:
        with pytest.raises(AtlasError) as e:
            engine.create(Actor("runtime", "rt"), employee_id=world.employee.id, objective="x")
        assert e.value.code == ErrorCode.UNAUTHORIZED
        parent = engine.create(world.owner, employee_id=world.employee.id, objective="pai")
        child = engine.create(
            Actor("runtime", "rt"), employee_id=world.employee.id, objective="filho", parent_task_id=parent
        )
        assert engine.get(child)["parent_task_id"] == parent

    def test_foreign_owner_cannot_create_for_employee(self, engine: TaskEngine, world: World) -> None:
        with pytest.raises(AtlasError):
            engine.create(Actor("owner", new_id(), "local_app"), employee_id=world.employee.id, objective="x")


class TestTransitions:
    def test_optimistic_version(self, engine: TaskEngine, world: World) -> None:
        tid = engine.create(world.owner, employee_id=world.employee.id, objective="x")
        engine.transition(tid, S.UNDERSTANDING, expected_version=1, actor=world.owner, reason="r")
        with pytest.raises(AtlasError) as e:
            engine.transition(tid, S.PLANNING, expected_version=1, actor=world.owner, reason="stale")
        assert e.value.code == ErrorCode.VERSION_CONFLICT

    def test_invalid_transition_rejected(self, engine: TaskEngine, world: World) -> None:
        from runtime.tasks.state_machine import InvalidTransition

        tid = engine.create(world.owner, employee_id=world.employee.id, objective="x")
        with pytest.raises(InvalidTransition):
            engine.transition(tid, S.RUNNING, expected_version=1, actor=world.owner, reason="skip")

    def test_blocked_requires_reason(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        v = engine.get(tid)["version"]
        with pytest.raises(AtlasError):
            engine.transition(tid, S.BLOCKED, expected_version=v, actor=world.owner, reason="x")
        engine.transition(
            tid,
            S.BLOCKED,
            expected_version=v,
            actor=world.owner,
            reason="x",
            blocked_reason="WORKSPACE_OFFLINE",
        )
        validate("task", engine.get(tid))

    def test_completed_only_through_complete(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        with pytest.raises(AtlasError):
            engine.transition(
                tid, S.COMPLETED, expected_version=engine.get(tid)["version"], actor=world.owner, reason="x"
            )


class TestLeases:
    def test_acquire_heartbeat_release(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        lease = engine.acquire_lease(tid, "w1")
        assert engine.get(tid)["state"] == "RUNNING"
        world.clock.advance(seconds=30)
        lease = engine.heartbeat(lease)
        engine.release(lease, S.VERIFYING, "step done")
        assert engine.get(tid)["state"] == "VERIFYING"

    def test_second_worker_cannot_steal_live_lease(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        engine.acquire_lease(tid, "w1")
        with pytest.raises(AtlasError):
            engine.acquire_lease(tid, "w2")

    def test_expired_lease_is_fenced(self, engine: TaskEngine, world: World) -> None:
        """Spec 9.3: a stale worker loses dispatch authority when another takes over."""
        tid = make_ready(engine, world)
        old = engine.acquire_lease(tid, "w1")
        world.clock.advance(seconds=61)
        new = engine.acquire_lease(tid, "w2")
        assert new.fencing_token > old.fencing_token
        with pytest.raises(AtlasError) as e:
            engine.heartbeat(old)
        assert e.value.code == ErrorCode.UNAUTHORIZED
        with transaction(world.conn), pytest.raises(AtlasError):
            engine.check_lease_in_txn(tid, "w1", old.fencing_token)
        with transaction(world.conn):
            engine.check_lease_in_txn(tid, "w2", new.fencing_token)

    def test_leaving_running_bumps_token(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        lease = engine.acquire_lease(tid, "w1")
        engine.release(lease, S.READY, "yield")
        with transaction(world.conn), pytest.raises(AtlasError):
            engine.check_lease_in_txn(tid, "w1", lease.fencing_token)

    def test_only_ready_tasks_can_be_leased(self, engine: TaskEngine, world: World) -> None:
        tid = engine.create(world.owner, employee_id=world.employee.id, objective="x")
        with pytest.raises(AtlasError):
            engine.acquire_lease(tid, "w1")


class TestOwnerControls:
    def test_pause_revokes_lease_and_resume_reevaluates(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        lease = engine.acquire_lease(tid, "w1")
        engine.pause(tid, actor=world.owner, expected_version=engine.get(tid)["version"])
        assert engine.get(tid)["state"] == "PAUSED"
        with transaction(world.conn), pytest.raises(AtlasError):
            engine.check_lease_in_txn(tid, "w1", lease.fencing_token)
        state = engine.resume(tid, actor=world.owner, expected_version=engine.get(tid)["version"])
        assert state == S.READY

    def test_resume_with_unknown_effect_goes_to_blocked(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world, external_writes=True)
        engine.pause(tid, actor=world.owner, expected_version=engine.get(tid)["version"])
        with transaction(world.conn):
            insert_action(world.conn, tid, status="UNKNOWN")
        state = engine.resume(tid, actor=world.owner, expected_version=engine.get(tid)["version"])
        assert state == S.BLOCKED
        assert engine.get(tid)["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN"

    def test_non_owner_cannot_pause(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        for actor in (Actor("runtime", "rt"), Actor("owner", new_id(), "local_app")):
            with pytest.raises(AtlasError) as e:
                engine.pause(tid, actor=actor, expected_version=engine.get(tid)["version"])
            assert e.value.code == ErrorCode.UNAUTHORIZED

    def test_cancel_preserves_past_effects(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world, external_writes=True)
        with transaction(world.conn):
            done = insert_action(world.conn, tid, status="CONFIRMED")
            pending = insert_action(world.conn, tid, status="PROPOSED")
            unknown = insert_action(world.conn, tid, status="UNKNOWN")
        rep = engine.cancel(tid, actor=world.owner, expected_version=engine.get(tid)["version"])
        assert rep.effects_already_happened == [done]
        assert rep.cancelled_actions == [pending]
        assert rep.effects_uncertain == [unknown]
        status = dict(world.conn.execute("SELECT id, status FROM actions").fetchall())
        assert status[done] == "CONFIRMED"  # never rewritten
        assert status[unknown] == "UNKNOWN"
        assert engine.get(tid)["state"] == "CANCELLED"

    def test_stop_all_under_two_seconds(self, engine: TaskEngine, world: World) -> None:
        """GA-12 / spec 12.3: target is < 2 s to stop new dispatches in the local test environment."""
        tids = [make_ready(engine, world) for _ in range(25)]
        leases = [engine.acquire_lease(t, f"w{i}") for i, t in enumerate(tids[:10])]
        rep = engine.stop_all(actor=world.owner, employee_id=world.employee.id)
        assert len(rep.paused_tasks) == 25
        assert rep.elapsed_ms < 2000
        for lease in leases:
            with transaction(world.conn), pytest.raises(AtlasError):
                engine.check_lease_in_txn(lease.task_id, lease.worker_id, lease.fencing_token)

    def test_stop_all_requires_owner(self, engine: TaskEngine, world: World) -> None:
        with pytest.raises(AtlasError):
            engine.stop_all(actor=Actor("runtime", "rt"), employee_id=world.employee.id)


class TestCompletion:
    def _verifying(self, engine: TaskEngine, world: World) -> str:
        tid = engine.create(
            world.owner,
            employee_id=world.employee.id,
            objective="x",
            criteria=[("Relatorio abre", True), ("Opcional", False)],
        )
        for to in (S.UNDERSTANDING, S.PLANNING, S.READY):
            engine.transition(
                tid, to, expected_version=engine.get(tid)["version"], actor=world.owner, reason="t"
            )
        lease = engine.acquire_lease(tid, "w1")
        engine.release(lease, S.VERIFYING, "verify")
        return tid

    def test_cannot_complete_with_unsatisfied_required_criteria(
        self, engine: TaskEngine, world: World
    ) -> None:
        tid = self._verifying(engine, world)
        with pytest.raises(AtlasError, match="Relatorio abre"):
            engine.complete(tid, actor=world.owner, expected_version=engine.get(tid)["version"])

    def test_completes_with_evidence(self, engine: TaskEngine, world: World) -> None:
        tid = self._verifying(engine, world)
        ev = new_id()
        with transaction(world.conn):
            world.conn.execute(
                "INSERT INTO evidence(id, task_id, kind, summary, created_at) VALUES (?,?,?,?,?)",
                (ev, tid, "file_opens", "arquivo aberto e hash conferido", "2026-01-01T00:00:00.000Z"),
            )
        required = next(c for c in engine.get(tid)["completion_criteria"] if c["required"])
        engine.satisfy_criterion(tid, required["criterion_id"], ev)
        engine.complete(tid, actor=world.owner, expected_version=engine.get(tid)["version"])
        assert engine.get(tid)["state"] == "COMPLETED"

    def test_criterion_needs_real_evidence(self, engine: TaskEngine, world: World) -> None:
        tid = self._verifying(engine, world)
        crit = engine.get(tid)["completion_criteria"][0]["criterion_id"]
        with pytest.raises(AtlasError):
            engine.satisfy_criterion(tid, crit, new_id())

    def test_checkpoint_rejects_private_reasoning(self, engine: TaskEngine, world: World) -> None:
        tid = make_ready(engine, world)
        engine.checkpoint(tid, {"step": 2, "next": "gerar relatorio"})
        with pytest.raises(AtlasError):
            engine.checkpoint(tid, {"step": 2, "chain_of_thought": "..."})


class TestRecovery:
    def test_restart_marks_in_flight_unknown_and_does_not_redispatch(
        self, engine: TaskEngine, world: World
    ) -> None:
        t_busy = make_ready(engine, world, external_writes=True)
        t_idle = make_ready(engine, world)
        engine.acquire_lease(t_busy, "w1")
        engine.acquire_lease(t_idle, "w2")
        with transaction(world.conn):
            a = insert_action(world.conn, t_busy, status="DISPATCHING")
        rep = engine.recover_after_restart()
        assert rep.actions_marked_unknown == [a]
        assert engine.get(t_busy)["state"] == "BLOCKED"
        assert engine.get(t_busy)["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN"
        assert engine.get(t_idle)["state"] == "READY"
        assert world.conn.execute("SELECT status FROM actions WHERE id=?", (a,)).fetchone()[0] == "UNKNOWN"
        # Still blocked until reconciled.
        assert engine.unblock_if_resolved(t_busy, actor=world.owner) == S.BLOCKED
        with transaction(world.conn):
            world.conn.execute("UPDATE actions SET status='CONFIRMED' WHERE id=?", (a,))
        assert engine.unblock_if_resolved(t_busy, actor=world.owner) == S.READY
