"""AT-008.1, AT-017.2, GA-06, GA-07 and threats T-03, T-06, T-07: dispatch through the broker."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest

from security.approvals.mandates import MandateStore
from shared.actors import Actor
from shared.clock import to_utc_str
from shared.errors import AtlasError, ErrorCode
from storage import journal
from storage.store import open_store
from tests.control_plane import OWNER_CHANNEL, ControlPlane

PAIRED = "paired_device"


def email(to: str = "cliente@example.test", body: str = "Segue o relatorio.") -> dict[str, Any]:
    return {"to": to, "subject": "Relatorio", "body": body}


def approve(cp: ControlPlane, approval: dict[str, Any], actor: Actor | None = None) -> dict[str, Any]:
    return cp.broker.decide_approval(
        approval["approval_id"],
        actor=actor or cp.world.owner,
        approve=True,
        params_hash=approval["params_hash"],
        nonce=approval["nonce"],
    )


def action_status(cp: ControlPlane, action_id: str) -> str:
    return str(cp.world.conn.execute("SELECT status FROM actions WHERE id = ?", (action_id,)).fetchone()[0])


class TestAllowPath:
    def test_owner_channel_delivery_is_allowed_and_receipted(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        lease = cp.lease(tid)
        res = cp.broker.submit(
            cp.proposal(
                tid, "messaging.send_owner_artifact", {"recipient_ref": OWNER_CHANNEL, "message": "Pronto"}
            ),
            lease,
        )
        assert res.status == "CONFIRMED"
        assert res.tool_result is not None and res.tool_result["external_reference"] == "fake-receipt-1"
        assert len(cp.fake.sent) == 1
        assert cp.fake.sent[0]["idempotency_key"] == res.action_id
        receipts = cp.world.conn.execute("SELECT COUNT(*) FROM external_receipts").fetchone()[0]
        assert receipts == 1
        types = [e["type"] for e in journal.events_after(cp.world.conn, cp.world.employee.id, 0)]
        assert "action.dispatching" in types and "action.confirmed" in types

    def test_success_without_receipt_is_unknown_not_confirmed(self, cp: ControlPlane) -> None:
        """Spec 13.7: success=true alone is not proof of an external effect."""
        cp.fake.mode = "no_receipt"
        tid = cp.ready_task()
        res = cp.broker.submit(
            cp.proposal(
                tid, "messaging.send_owner_artifact", {"recipient_ref": OWNER_CHANNEL, "message": "x"}
            ),
            cp.lease(tid),
        )
        assert res.status == "UNKNOWN"
        assert cp.tasks.get(tid)["state"] == "BLOCKED"
        assert cp.tasks.get(tid)["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN"


class TestApprovalFlow:
    def test_r3_requires_approval_then_dispatches_once(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        prop = cp.proposal(tid, "email.send_external", email())
        res = cp.broker.submit(prop, cp.lease(tid))
        assert res.status == "APPROVAL_REQUIRED"
        assert cp.fake.sent == []
        assert cp.tasks.get(tid)["state"] == "WAITING_APPROVAL"
        approve(cp, res.approval)  # type: ignore[arg-type]
        assert cp.tasks.get(tid)["state"] == "READY"
        res2 = cp.broker.submit(prop, cp.lease(tid, "w2"))
        assert res2.status == "CONFIRMED"
        assert res2.action_id == res.action_id  # same action, not a new one
        assert len(cp.fake.sent) == 1

    def test_replay_after_consumption_does_not_resend(self, cp: ControlPlane) -> None:
        """T-06: a repeated approval/proposal does not repeat the send."""
        tid = cp.ready_task()
        prop = cp.proposal(tid, "email.send_external", email())
        res = cp.broker.submit(prop, cp.lease(tid))
        approve(cp, res.approval)  # type: ignore[arg-type]
        lease = cp.lease(tid, "w2")
        assert cp.broker.submit(prop, lease).status == "CONFIRMED"
        again = cp.broker.submit(prop, lease)
        assert again.status == "APPROVAL_REQUIRED"  # a brand new approval would be needed
        assert len(cp.fake.sent) == 1
        with pytest.raises(AtlasError):
            approve(cp, res.approval)  # type: ignore[arg-type]

    def test_material_change_requires_new_approval(self, cp: ControlPlane) -> None:
        """GA-07: after approval, a different recipient or content is a different action."""
        tid = cp.ready_task()
        res = cp.broker.submit(cp.proposal(tid, "email.send_external", email()), cp.lease(tid))
        approve(cp, res.approval)  # type: ignore[arg-type]
        changed = cp.broker.submit(
            cp.proposal(tid, "email.send_external", email(to="outro@example.test")), cp.lease(tid, "w2")
        )
        assert changed.status == "APPROVAL_REQUIRED"
        assert changed.action_id != res.action_id
        assert cp.fake.sent == []

    def test_owner_rejection_cancels_action(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        prop = cp.proposal(tid, "email.send_external", email())
        res = cp.broker.submit(prop, cp.lease(tid))
        ap = res.approval
        assert ap is not None
        cp.broker.decide_approval(
            ap["approval_id"],
            actor=cp.world.owner,
            approve=False,
            params_hash=ap["params_hash"],
            nonce=ap["nonce"],
        )
        res2 = cp.broker.submit(prop, cp.lease(tid, "w2"))
        assert res2.status == "REJECTED"
        assert action_status(cp, res.action_id) == "CANCELLED_BEFORE_DISPATCH"  # type: ignore[arg-type]
        assert cp.fake.sent == []

    def test_decision_must_match_presented_hash_and_nonce(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        res = cp.broker.submit(cp.proposal(tid, "email.send_external", email()), cp.lease(tid))
        ap = res.approval
        assert ap is not None
        for ph, nonce in ((("0" * 64), ap["nonce"]), (ap["params_hash"], "f" * 32)):
            with pytest.raises(AtlasError):
                cp.broker.decide_approval(
                    ap["approval_id"], actor=cp.world.owner, approve=True, params_hash=ph, nonce=nonce
                )

    def test_expired_approval_is_not_usable(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        prop = cp.proposal(tid, "email.send_external", email())
        res = cp.broker.submit(prop, cp.lease(tid))
        approve(cp, res.approval)  # type: ignore[arg-type]
        cp.world.clock.advance(hours=25)
        res2 = cp.broker.submit(prop, cp.lease(tid, "w2"))
        assert res2.status == "APPROVAL_REQUIRED"  # expired approval replaced by a fresh request
        assert cp.fake.sent == []

    def test_only_owner_decides(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        res = cp.broker.submit(cp.proposal(tid, "email.send_external", email()), cp.lease(tid))
        for actor in (
            Actor("runtime", "rt"),
            Actor("worker", "w1"),
            Actor("device", "phone", PAIRED),
            Actor("owner", cp.world.owner_id, "email"),
        ):
            with pytest.raises(AtlasError) as e:
                approve(cp, res.approval, actor)  # type: ignore[arg-type]
            assert e.value.code == ErrorCode.UNAUTHORIZED


class TestPurchases:
    def purchase(self, total: int = 12990) -> dict[str, Any]:
        return {
            "vendor": "loja-sandbox.example.test",
            "items": ["licenca sintetica"],
            "total": {"amount_minor": total, "currency": "BRL"},
            "known_fees": [{"amount_minor": 990, "currency": "BRL"}],
            "material_terms": "sem renovacao",
        }

    def test_purchase_needs_task_permission(self, cp: ControlPlane) -> None:
        tid = cp.ready_task(purchases=False)
        res = cp.broker.submit(cp.proposal(tid, "commerce.purchase", self.purchase()), cp.lease(tid))
        assert (res.status, res.reason) == ("DENIED", "TASK_FORBIDS_PURCHASES")

    def test_r4_needs_strong_local_confirmation(self, cp: ControlPlane) -> None:
        """GA-06: nothing is bought before a valid approval; a paired phone cannot approve R4."""
        tid = cp.ready_task(purchases=True)
        prop = cp.proposal(tid, "commerce.purchase", self.purchase())
        res = cp.broker.submit(prop, cp.lease(tid))
        assert res.status == "APPROVAL_REQUIRED"
        ap = res.approval
        assert ap is not None
        assert ap["purchase"]["vendor"] == "loja-sandbox.example.test"
        assert ap["max_cost"] == {"amount_minor": 12990, "currency": "BRL"}
        phone = Actor("owner", cp.world.owner_id, PAIRED, strong_auth=True)
        weak_local = Actor("owner", cp.world.owner_id, "local_app", strong_auth=False)
        for actor in (phone, weak_local):
            with pytest.raises(AtlasError, match="R4"):
                approve(cp, ap, actor)
        approve(cp, ap)  # local app, strong auth
        assert cp.broker.submit(prop, cp.lease(tid, "w2")).status == "CONFIRMED"
        assert len(cp.fake.sent) == 1

    def test_price_increase_invalidates_approval(self, cp: ControlPlane) -> None:
        tid = cp.ready_task(purchases=True)
        res = cp.broker.submit(cp.proposal(tid, "commerce.purchase", self.purchase(12990)), cp.lease(tid))
        approve(cp, res.approval)  # type: ignore[arg-type]
        res2 = cp.broker.submit(
            cp.proposal(tid, "commerce.purchase", self.purchase(13990)), cp.lease(tid, "w2")
        )
        assert res2.status == "APPROVAL_REQUIRED"
        assert cp.fake.sent == []


class TestWorkersAndLeases:
    def test_stale_worker_cannot_dispatch(self, cp: ControlPlane) -> None:
        """T-07: the old worker loses dispatch authority after another takes over."""
        tid = cp.ready_task()
        old = cp.lease(tid, "old")
        cp.world.clock.advance(seconds=61)
        cp.lease(tid, "new")
        with pytest.raises(AtlasError) as e:
            cp.broker.submit(
                cp.proposal(
                    tid, "messaging.send_owner_artifact", {"recipient_ref": OWNER_CHANNEL, "message": "x"}
                ),
                old,
            )
        assert e.value.code == ErrorCode.UNAUTHORIZED
        assert cp.fake.sent == []
        types = [e["type"] for e in journal.events_after(cp.world.conn, cp.world.employee.id, 0)]
        assert "action.rejected" in types

    def test_stop_all_blocks_next_dispatch(self, cp: ControlPlane) -> None:
        """GA-12: after an authenticated stop, no new dispatch happens."""
        tid = cp.ready_task()
        lease = cp.lease(tid)
        cp.tasks.stop_all(actor=cp.world.owner, employee_id=cp.world.employee.id)
        with pytest.raises(AtlasError):
            cp.broker.submit(
                cp.proposal(
                    tid, "messaging.send_owner_artifact", {"recipient_ref": OWNER_CHANNEL, "message": "x"}
                ),
                lease,
            )
        assert cp.fake.sent == []

    def test_proposal_for_other_task_rejected(self, cp: ControlPlane) -> None:
        t1, t2 = cp.ready_task(), cp.ready_task()
        with pytest.raises(AtlasError):
            cp.broker.submit(
                cp.proposal(
                    t2, "messaging.send_owner_artifact", {"recipient_ref": OWNER_CHANNEL, "message": "x"}
                ),
                cp.lease(t1),
            )

    def test_concurrent_dispatch_of_same_approved_action_sends_once(self, cp: ControlPlane) -> None:
        """T-06: race between two connections consuming the same approval."""
        tid = cp.ready_task()
        prop = cp.proposal(tid, "email.send_external", email())
        res = cp.broker.submit(prop, cp.lease(tid))
        approve(cp, res.approval)  # type: ignore[arg-type]
        lease = cp.lease(tid, "w2")
        results: list[str] = []
        errors: list[str] = []

        def run() -> None:
            from security.broker.broker import Broker
            from security.budget.budget import BudgetManager

            conn = open_store(cp.world.path, cp.world.clock)
            try:
                b = Broker(
                    conn,
                    cp.world.clock,
                    registry=_rebind(cp, conn),
                    policy=cp.broker.policy,
                    budget=BudgetManager(conn, cp.world.clock, cp.broker.budget.limits),
                    owner_channels=cp.broker.owner_channels,
                )
                results.append(b.submit(prop, lease).status)
            except AtlasError as exc:
                errors.append(str(exc.code))
            finally:
                conn.close()

        threads = [threading.Thread(target=run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(cp.fake.sent) == 1
        assert results.count("CONFIRMED") == 1


def _rebind(cp: ControlPlane, conn: Any) -> Any:
    from runtime.tools.registry import ToolRegistry
    from tests.fakes.adapters import EMAIL_SEND

    reg = ToolRegistry(conn, cp.world.clock)
    reg.register(EMAIL_SEND, cp.fake.adapter("email"))
    return reg


class TestMandates:
    def test_mandate_allows_bounded_r3_without_asking(self, cp: ControlPlane) -> None:
        store = MandateStore(cp.world.conn, cp.world.clock)
        expires = to_utc_str(cp.world.clock.now() + timedelta(days=7))
        store.create(
            actor=cp.world.owner,
            employee_id=cp.world.employee.id,
            tool_id="email.send_external",
            destination_pattern="*@empresa-parceira.example.test",
            max_risk="R3",
            max_uses=2,
            expires_at=expires,
        )
        tid = cp.ready_task()
        lease = cp.lease(tid)
        for i in range(2):
            r = cp.broker.submit(
                cp.proposal(
                    tid,
                    "email.send_external",
                    email(to="compras@empresa-parceira.example.test", body=f"n{i}"),
                ),
                lease,
            )
            assert r.status == "CONFIRMED"
        third = cp.broker.submit(
            cp.proposal(
                tid, "email.send_external", email(to="compras@empresa-parceira.example.test", body="n3")
            ),
            lease,
        )
        assert third.status == "APPROVAL_REQUIRED"  # uses exhausted
        assert len(cp.fake.sent) == 2

    def test_mandate_rules(self, cp: ControlPlane) -> None:
        store = MandateStore(cp.world.conn, cp.world.clock)
        expires = to_utc_str(cp.world.clock.now() + timedelta(days=1))
        common = {
            "employee_id": cp.world.employee.id,
            "tool_id": "email.send_external",
            "max_uses": 1,
            "expires_at": expires,
        }
        with pytest.raises(AtlasError):
            store.create(actor=cp.world.owner, destination_pattern="*@x.test", max_risk="R4", **common)
        with pytest.raises(AtlasError):
            store.create(actor=cp.world.owner, destination_pattern="*", max_risk="R3", **common)
        with pytest.raises(AtlasError):
            store.create(
                actor=Actor("runtime", "rt"), destination_pattern="*@x.test", max_risk="R3", **common
            )


class TestBudgetInBroker:
    def test_paid_tool_respects_task_budget(self, cp: ControlPlane) -> None:
        tid = cp.ready_task(external_writes=False)
        lease = cp.lease(tid)
        q = {"query": "precos", "max_cost": {"amount_minor": 3000, "currency": "USD"}}
        assert cp.broker.submit(cp.proposal(tid, "research.paid_search", q), lease).status == "CONFIRMED"
        res = cp.broker.submit(cp.proposal(tid, "research.paid_search", {**q, "query": "outra"}), lease)
        assert (res.status, res.reason) == ("BUDGET_EXCEEDED", "TASK_LIMIT")
        assert cp.tasks.get(tid)["state"] == "BLOCKED"
        assert cp.tasks.get(tid)["blocked_reason"] == "BUDGET_EXCEEDED"

    def test_failed_before_send_releases_reservation(self, cp: ControlPlane) -> None:
        cp.fake.mode = "fail_before_send"
        tid = cp.ready_task(external_writes=False)
        q = {"query": "precos", "max_cost": {"amount_minor": 3000, "currency": "USD"}}
        res = cp.broker.submit(cp.proposal(tid, "research.paid_search", q), cp.lease(tid))
        assert res.status == "FAILED"
        assert res.tool_result is not None and res.tool_result["retry_class"] == "TRANSIENT"
        st = cp.world.conn.execute("SELECT status FROM budget_reservations").fetchone()[0]
        assert st == "RELEASED"


class TestContracts:
    def test_invalid_proposal_rejected_before_anything_is_written(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        prop = cp.proposal(
            tid, "messaging.send_owner_artifact", {"recipient_ref": OWNER_CHANNEL, "message": "x"}
        )
        prop["effect"] = "READ_ONLY"
        with pytest.raises(AtlasError) as e:
            cp.broker.submit(prop, cp.lease(tid))
        assert e.value.code == ErrorCode.INVALID_INPUT
        assert cp.world.conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0

    def test_tool_input_validated_against_manifest(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        prop = cp.proposal(tid, "email.send_external", {**email(), "bcc": "leak@example.test"})
        with pytest.raises(AtlasError, match="tool input invalid"):
            cp.broker.submit(prop, cp.lease(tid))

    def test_unregistered_tool_denied(self, cp: ControlPlane) -> None:
        tid = cp.ready_task()
        with pytest.raises(AtlasError) as e:
            cp.broker.submit(cp.proposal(tid, "host.shell", {"cmd": "id"}), cp.lease(tid))
        assert e.value.code == ErrorCode.POLICY_DENIED

    def test_tool_result_is_contract_valid(self, cp: ControlPlane) -> None:
        from shared.contracts import errors_for

        tid = cp.ready_task()
        res = cp.broker.submit(
            cp.proposal(
                tid, "messaging.send_owner_artifact", {"recipient_ref": OWNER_CHANNEL, "message": "x"}
            ),
            cp.lease(tid),
        )
        assert errors_for("tool_result", res.tool_result) == []
