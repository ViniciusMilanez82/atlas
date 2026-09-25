"""R5-09 (P2; N18): a capability decision is one local transaction - decision + content hash, the
instruction that tells the worker, the task back in the queue and the owner notice - or nothing.
Resending the same decision returns the consolidated result; a different one conflicts. Failures are
injected after each write, at the commit and across a restart. Nothing is ever bought.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.capabilities.requests import CapabilityRequests
from runtime.tasks.state_machine import TaskState
from shared.actors import Actor
from shared.errors import AtlasError
from storage.store import open_store
from tests.regression.r5_harness import R5World

REQ = {
    "missing_capability": "pesquisa web", "problem": "Sem ferramenta de pesquisa", "provider": "Fictício",
    "evidence": "fixture sintética", "price": {"amount": "10", "currency": "USD", "recurrence": "once",
                                              "source": "fixture"},
    "data_shared": [], "alternatives": ["fonte pública"], "risk": "teste", "test_plan": "teste controlado",
}


def _filed(r5: R5World, request: dict[str, Any] | None = None) -> tuple[str, str]:
    tid = r5.create("Prepare relatório de pesquisa sobre fornecedores.")
    r5.runner._prepare(tid)
    lease = r5.tasks.acquire_lease(tid, "resource-worker")
    rid = CapabilityRequests(r5.conn, r5.clock).file(
        task_id=tid, worker=Actor("worker", lease.worker_id, "internal"), request=request or REQ
    )
    assert r5.state(tid) == TaskState.WAITING_USER
    return tid, rid


def _nothing_bought(r5: R5World) -> None:
    assert r5.conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0
    assert r5.conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


@pytest.mark.parametrize("where", ["update_instruction_in_txn", "transition_in_txn", "enqueue", "journal"])
def test_failure_after_any_write_leaves_nothing_half_done(r5: R5World, where: str, monkeypatch: Any) -> None:
    tid, rid = _filed(r5)
    cr = CapabilityRequests(r5.conn, r5.clock)

    def boom(*a: Any, **k: Any) -> Any:
        raise OSError(f"injected failure in {where}")

    if where == "enqueue":
        monkeypatch.setattr("runtime.capabilities.requests.enqueue_in_txn", boom)
    elif where == "journal":
        monkeypatch.setattr("runtime.capabilities.requests.journal.append", boom)
    else:
        monkeypatch.setattr(cr.tasks, where, boom)
    with pytest.raises(OSError):
        cr.decide(rid, actor=r5.owner, approve=True)
    row = r5.conn.execute("SELECT status FROM capability_requests WHERE id = ?", (rid,)).fetchone()
    assert row[0] == "PENDING"  # the reviewer's case: APPROVED persisted while the task stayed stuck
    assert r5.state(tid) == TaskState.WAITING_USER and r5.tasks.get(tid)["instruction_revision"] == 1
    monkeypatch.undo()
    out = CapabilityRequests(r5.conn, r5.clock).decide(rid, actor=r5.owner, approve=True)  # the retry works
    assert out["status"] == "APPROVED" and r5.state(tid) == TaskState.READY
    _nothing_bought(r5)


def test_crash_after_commit_then_restart_and_resend_returns_the_same_result(r5: R5World) -> None:
    tid, rid = _filed(r5)
    first = CapabilityRequests(r5.conn, r5.clock).decide(rid, actor=r5.owner, approve=True, note="ok")
    # the reply was lost; the service restarts on a fresh connection and the app resends
    conn2 = open_store(r5.root / "atlas.sqlite", r5.clock)
    again = CapabilityRequests(conn2, r5.clock).decide(rid, actor=r5.owner, approve=True, note="ok")
    conn2.close()
    assert again["replayed"] and again["instruction_revision"] == first["instruction_revision"]
    assert r5.tasks.get(tid)["instruction_revision"] == 2  # one instruction, not two
    assert r5.conn.execute(
        "SELECT COUNT(*) FROM notification_outbox WHERE task_id = ? AND kind = 'status'", (tid,)
    ).fetchone()[0] == 1
    with pytest.raises(AtlasError, match="different decision"):
        CapabilityRequests(r5.conn, r5.clock).decide(rid, actor=r5.owner, approve=False)
    _nothing_bought(r5)


def test_legacy_decision_without_its_instruction_is_completed_by_the_same_resend(r5: R5World) -> None:
    tid, rid = _filed(r5)
    with r5.conn:  # what the pre-fix code left behind: APPROVED, no instruction, task WAITING_USER
        r5.conn.execute("UPDATE capability_requests SET status = 'APPROVED' WHERE id = ?", (rid,))
    out = CapabilityRequests(r5.conn, r5.clock).decide(rid, actor=r5.owner, approve=True)
    assert out["status"] == "APPROVED" and out["instruction_revision"] == 2
    assert r5.state(tid) == TaskState.READY


def test_rejection_expiry_new_conditions_and_cancelled_task(r5: R5World) -> None:
    tid, rid = _filed(r5)
    out = CapabilityRequests(r5.conn, r5.clock).decide(rid, actor=r5.owner, approve=False, note="use e-mail")
    assert out["status"] == "REJECTED" and "RECUSOU" in r5.tasks.instructions(tid)[-1]["instruction"]

    tid2, old = _filed(r5)  # the worker re-quotes with a different price before the owner decides
    lease = r5.tasks.get(tid2)
    assert lease["state"] == TaskState.WAITING_USER
    new = CapabilityRequests(r5.conn, r5.clock).file(
        task_id=tid2, worker=Actor("worker", "w", "internal"),
        request={**REQ, "price": {**REQ["price"], "amount": "25"}},
    )
    with pytest.raises(AtlasError, match="superseded"):
        CapabilityRequests(r5.conn, r5.clock).decide(old, actor=r5.owner, approve=True)
    r5.clock.advance(days=8)  # the new quote is now too old to approve as is
    out = CapabilityRequests(r5.conn, r5.clock).decide(new, actor=r5.owner, approve=True)
    assert out["status"] == "EXPIRED" and r5.state(tid2) == TaskState.WAITING_USER

    tid3, rid3 = _filed(r5)
    r5.tasks.cancel(tid3, actor=r5.owner, expected_version=r5.tasks.get(tid3)["version"])
    out = CapabilityRequests(r5.conn, r5.clock).decide(rid3, actor=r5.owner, approve=True)
    assert out["status"] == "CANCELLED" and r5.state(tid3) == TaskState.CANCELLED
    _nothing_bought(r5)


def test_only_the_owner_decides(r5: R5World) -> None:
    _, rid = _filed(r5)
    with pytest.raises(AtlasError):
        CapabilityRequests(r5.conn, r5.clock).decide(rid, actor=Actor("runtime", "x", "internal"), approve=True)
