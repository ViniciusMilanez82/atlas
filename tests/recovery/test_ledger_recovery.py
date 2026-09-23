"""GA-10 / AT-017 / T-08: a crash after sending never causes a blind resend."""

from __future__ import annotations

import pytest

from shared.actors import Actor
from shared.errors import AtlasError
from tests.control_plane import ControlPlane


def email() -> dict[str, str]:
    return {"to": "cliente@example.test", "subject": "Proposta", "body": "Segue proposta sintetica."}


def approve(cp: ControlPlane, ap: dict[str, str]) -> None:
    cp.broker.decide_approval(
        ap["approval_id"],
        actor=cp.world.owner,
        approve=True,
        params_hash=ap["params_hash"],
        nonce=ap["nonce"],
    )


def test_crash_after_send_marks_unknown_and_never_resends(cp: ControlPlane) -> None:
    tid = cp.ready_task()
    prop = cp.proposal(tid, "email.send_external", email())
    first = cp.broker.submit(prop, cp.lease(tid))
    approve(cp, first.approval)  # type: ignore[arg-type]
    cp.fake.mode = "crash_after_send"
    res = cp.broker.submit(prop, cp.lease(tid, "w2"))
    assert res.status == "UNKNOWN"
    assert len(cp.fake.sent) == 1  # the e-mail did go out
    assert cp.tasks.get(tid)["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN"
    # approval is held, not reusable
    ap = cp.broker.approvals.get(first.approval["approval_id"])  # type: ignore[index]
    assert ap["status"] == "RESERVED"

    # Restart: nothing is re-dispatched and the task stays blocked.
    cp.fake.mode = "ok"
    rep = cp.tasks.recover_after_restart()
    assert tid not in rep.tasks_ready
    with pytest.raises(AtlasError):
        cp.broker.submit(prop, cp.lease(tid, "w3"))  # task is BLOCKED, cannot be leased
    assert len(cp.fake.sent) == 1


def test_reconciliation_confirms_and_unblocks(cp: ControlPlane) -> None:
    tid = cp.ready_task()
    prop = cp.proposal(tid, "email.send_external", email())
    first = cp.broker.submit(prop, cp.lease(tid))
    approve(cp, first.approval)  # type: ignore[arg-type]
    cp.fake.mode = "crash_after_send"
    res = cp.broker.submit(prop, cp.lease(tid, "w2"))
    final = cp.broker.reconcile(
        res.action_id,
        actor=cp.world.owner,
        happened=True,  # type: ignore[arg-type]
        evidence="mensagem encontrada na pasta Enviados (id sintetico 42)",
        external_reference="sent-42",
    )
    assert final == "CONFIRMED"
    assert cp.tasks.get(tid)["state"] == "READY"
    assert cp.broker.approvals.get(first.approval["approval_id"])["status"] == "CONSUMED"  # type: ignore[index]
    assert len(cp.fake.sent) == 1


def test_reconciliation_proving_absence_allows_controlled_retry(cp: ControlPlane) -> None:
    tid = cp.ready_task()
    prop = cp.proposal(tid, "email.send_external", email())
    first = cp.broker.submit(prop, cp.lease(tid))
    approve(cp, first.approval)  # type: ignore[arg-type]
    cp.fake.mode = "crash_after_send"
    res = cp.broker.submit(prop, cp.lease(tid, "w2"))
    cp.fake.sent.clear()  # the provider confirms nothing was delivered (synthetic)
    final = cp.broker.reconcile(
        res.action_id,
        actor=cp.world.owner,
        happened=False,  # type: ignore[arg-type]
        evidence="provedor confirma: nenhuma mensagem com este id",
    )
    assert final == "FAILED"
    ap = cp.broker.approvals.get(first.approval["approval_id"])  # type: ignore[index]
    assert ap["status"] == "APPROVED"  # released only because absence was proven


def test_reconciliation_requires_evidence_and_authority(cp: ControlPlane) -> None:
    tid = cp.ready_task()
    prop = cp.proposal(tid, "email.send_external", email())
    first = cp.broker.submit(prop, cp.lease(tid))
    approve(cp, first.approval)  # type: ignore[arg-type]
    cp.fake.mode = "crash_after_send"
    res = cp.broker.submit(prop, cp.lease(tid, "w2"))
    with pytest.raises(AtlasError):
        cp.broker.reconcile(res.action_id, actor=cp.world.owner, happened=True, evidence="  ")  # type: ignore[arg-type]
    with pytest.raises(AtlasError):
        cp.broker.reconcile(
            res.action_id,
            actor=Actor("runtime", "rt"),
            happened=True,  # type: ignore[arg-type]
            evidence="o modelo acha que foi enviado",
        )


def test_cancel_after_send_reports_effect_and_keeps_it(cp: ControlPlane) -> None:
    tid = cp.ready_task()
    lease = cp.lease(tid)
    res = cp.broker.submit(
        cp.proposal(
            tid, "messaging.send_owner_artifact", {"recipient_ref": "owner-verified-channel", "message": "x"}
        ),
        lease,
    )
    assert res.status == "CONFIRMED"
    rep = cp.tasks.cancel(tid, actor=cp.world.owner, expected_version=cp.tasks.get(tid)["version"])
    assert rep.effects_already_happened == [res.action_id]
    assert len(cp.fake.sent) == 1
