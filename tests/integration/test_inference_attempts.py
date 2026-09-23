"""Review finding R-04: lifecycle of inference reservations (spec 7.4).

Every call is recorded before sending; outcomes distinguish not-sent, confirmed consumption and
unknown billing; nothing is released blindly and nothing stays open without a recovery path.
"""

from __future__ import annotations

import threading

import pytest

from runtime.models.pricing import SPEC_REFERENCE_TABLE
from runtime.models.router import BudgetedModelClient, CatalogEntry, Consent, ModelRouter, Requirements
from runtime.models.types import (
    Message,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ProviderCallError,
    ProviderErrorKind,
    Role,
    Usage,
)
from security.budget.budget import BudgetError, BudgetLimits, BudgetManager
from shared.actors import Actor
from shared.errors import AtlasError, ErrorCode
from shared.money import Money
from storage import journal
from storage.db import transaction
from storage.store import open_store
from tests.conftest import World
from tests.fakes.model_provider import FakeModelProvider
from tests.helpers import insert_task

CAPS = ModelCapabilities(
    structured_output=True, tool_calls=True, context_window_tokens=100_000, max_output_tokens=4_000
)
CATALOG = [
    CatalogEntry("openai", "gpt-6-sol", "general", 2, CAPS, True),
    CatalogEntry("openai", "gpt-6-astra", "deep", 3, CAPS, True),
    CatalogEntry("anthropic", "claude-opus-5-5", "general", 3, CAPS, True),
]
REQ = ModelRequest("x", (Message(Role.USER, "ola"),), max_output_tokens=500)


class ScriptedProvider(FakeModelProvider):
    """FAKE provider whose generate() can raise transport errors."""

    def __init__(self, provider_id: str, steps: list[object]) -> None:
        super().__init__(provider_id)
        self.steps = steps

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        step = self.steps.pop(0) if self.steps else "ok"
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, ModelResponse):
            return step
        self.script = [str(step)]
        self.calls.pop()
        return super().generate(request)


def make(
    world: World,
    providers: dict[str, FakeModelProvider],
    *,
    limits: BudgetLimits | None = None,
    consent: Consent | None = None,
) -> BudgetedModelClient:
    return BudgetedModelClient(
        world.conn,
        world.clock,
        ModelRouter(CATALOG, consent or Consent({"openai"})),
        providers,  # type: ignore[arg-type]
        SPEC_REFERENCE_TABLE,
        BudgetManager(world.conn, world.clock, limits or BudgetLimits("USD", 10_000, 5_000)),
    )


@pytest.fixture
def task_id(world: World) -> str:
    with transaction(world.conn):
        return insert_task(world.conn, world.owner_id, world.employee.id)


def attempts(world: World) -> list[tuple[str, str]]:
    return [
        (r["status"], r["rs"])
        for r in world.conn.execute(
            "SELECT a.status, b.status AS rs FROM inference_attempts a"
            " JOIN budget_reservations b ON b.id = a.reservation_id ORDER BY a.rowid"
        )
    ]


def test_attempt_is_persisted_before_sending(world: World, task_id: str) -> None:
    seen: list[list[tuple[str, str]]] = []

    class Spy(FakeModelProvider):
        def generate(self, request: ModelRequest) -> ModelResponse:
            seen.append(attempts(world))  # what is on disk at the moment of sending
            return super().generate(request)

    make(world, {"openai": Spy("openai")}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert seen == [[("IN_FLIGHT", "RESERVED")]]
    assert attempts(world) == [("SETTLED", "SETTLED")]


def test_transport_error_proven_not_sent_releases_and_falls_back(world: World, task_id: str) -> None:
    p = ScriptedProvider("openai", [ProviderCallError("connection refused", sent=False), "ok"])
    resp = make(world, {"openai": p}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert resp.model_id == "gpt-6-astra"
    assert attempts(world) == [("RELEASED", "RELEASED"), ("SETTLED", "SETTLED")]


def test_timeout_after_accept_keeps_reservation_unknown(world: World, task_id: str) -> None:
    p = ScriptedProvider("openai", [ProviderCallError("read timeout", sent=None), "ok"])
    make(world, {"openai": p}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert attempts(world)[0] == ("UNKNOWN", "RESERVED")
    types = [e["type"] for e in journal.events_after(world.conn, world.employee.id, 0)]
    assert "inference.billing_unknown" in types


def test_cancellation_is_unknown_and_stops(world: World, task_id: str) -> None:
    p = ScriptedProvider(
        "openai", [ProviderCallError("cancelled by owner", sent=None, kind=ProviderErrorKind.CANCELLED)]
    )
    with pytest.raises(AtlasError):
        make(world, {"openai": p}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert attempts(world) == [("UNKNOWN", "RESERVED")]
    assert len(p.calls) == 1  # no fallback after an owner cancel


def test_unexpected_adapter_exception_never_leaks_a_silent_reservation(world: World, task_id: str) -> None:
    p = ScriptedProvider("openai", [ConnectionResetError("socket closed")])
    with pytest.raises(AtlasError) as e:
        make(world, {"openai": p}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert e.value.persisted.startswith("attempt recorded as UNKNOWN")
    assert attempts(world) == [("UNKNOWN", "RESERVED")]


def test_crash_between_response_and_commit_is_recovered(world: World, task_id: str) -> None:
    client = make(world, {"openai": FakeModelProvider("openai")})

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("process died while committing")

    client.budget.settle_in_txn = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        client.call(task_id=task_id, req=Requirements(), request=REQ)
    assert attempts(world) == [("IN_FLIGHT", "RESERVED")]
    world.conn.close()
    world.conn = open_store(world.path, world.clock)
    restarted = make(world, {"openai": FakeModelProvider("openai")})
    assert len(restarted.recover_attempts()) == 1
    assert attempts(world) == [("UNKNOWN", "RESERVED")]


def test_missing_usage_is_estimated_then_reconciled(world: World, task_id: str) -> None:
    no_usage = ModelResponse("openai", "gpt-6-sol", "req-9", "ok", usage=None)
    client = make(world, {"openai": ScriptedProvider("openai", [no_usage])})
    resp = client.call(task_id=task_id, req=Requirements(), request=REQ)
    assert attempts(world) == [("ESTIMATED", "SETTLED")]
    reserved = world.conn.execute("SELECT amount_minor, settled_minor FROM budget_reservations").fetchone()
    assert reserved[0] == reserved[1] == resp.estimated_cost.amount_minor  # type: ignore[union-attr]
    attempt = world.conn.execute("SELECT id FROM inference_attempts").fetchone()[0]
    client.resolve_attempt(
        attempt, actor=world.owner, charged=Money(1, "USD"), evidence="relatorio de uso sintetico do provedor"
    )
    assert world.conn.execute("SELECT settled_minor FROM budget_reservations").fetchone()[0] == 1


def test_cost_above_estimate_is_settled_and_flagged(world: World, task_id: str) -> None:
    big = ModelResponse("openai", "gpt-6-sol", "req-1", "ok", usage=Usage(900_000, 0, 200_000))
    client = make(
        world, {"openai": ScriptedProvider("openai", [big])}, limits=BudgetLimits("USD", 100_000, 50_000)
    )
    resp = client.call(task_id=task_id, req=Requirements(), request=REQ)
    assert resp.estimated_cost == Money(380, "USD")  # 0.9M*2 + 0.2M*10 per million = 3.80 USD
    types = [e["type"] for e in journal.events_after(world.conn, world.employee.id, 0)]
    assert "budget.overrun" in types


def test_auth_error_releases_and_never_falls_back(world: World, task_id: str) -> None:
    p = FakeModelProvider("openai", script=["401"])
    with pytest.raises(AtlasError) as e:
        make(world, {"openai": p}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert e.value.code == ErrorCode.UNAUTHORIZED
    assert attempts(world) == [("RELEASED", "RELEASED")]


def test_rate_limit_is_not_billed(world: World, task_id: str) -> None:
    p = FakeModelProvider("openai", script=["429", "ok"])
    make(world, {"openai": p}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert attempts(world) == [("RELEASED", "RELEASED"), ("SETTLED", "SETTLED")]


def test_policy_refusal_billing_unknown_and_not_rerouted(world: World, task_id: str) -> None:
    p = FakeModelProvider("openai", script=["policy"])
    with pytest.raises(AtlasError) as e:
        make(world, {"openai": p}).call(task_id=task_id, req=Requirements(), request=REQ)
    assert e.value.code == ErrorCode.POLICY_DENIED
    assert attempts(world) == [("UNKNOWN", "RESERVED")]
    assert len(p.calls) == 1


def test_fallback_respects_budget_with_held_reservations(world: World, task_id: str) -> None:
    # Each reservation for 500 output tokens on gpt-6-sol is 1 cent; astra is 3 cents. Ceiling 3 cents.
    p = ScriptedProvider("openai", [ProviderCallError("gateway timeout", sent=None), "ok"])
    client = make(world, {"openai": p}, limits=BudgetLimits("USD", 3, 3))
    with pytest.raises(BudgetError):
        client.call(task_id=task_id, req=Requirements(), request=REQ)
    assert len(p.calls) == 1  # the fallback was never sent: the held reservation counts


def test_fallback_to_other_provider_requires_consent(world: World, task_id: str) -> None:
    openai = ScriptedProvider("openai", [ProviderCallError("down", sent=False)] * 2)
    anthropic = FakeModelProvider("anthropic")
    consent = Consent({"openai", "anthropic"}, cross_provider_fallback=False)
    with pytest.raises(AtlasError):
        make(world, {"openai": openai, "anthropic": anthropic}, consent=consent).call(
            task_id=task_id, req=Requirements(), request=REQ
        )
    assert anthropic.calls == []


def test_two_concurrent_calls_respect_the_ceiling(world: World, task_id: str) -> None:
    """Two workers race; the monthly ceiling fits exactly one reservation of the default model."""
    limits = BudgetLimits("USD", 1, 1)
    sent: list[str] = []
    errors: list[str] = []
    gate = threading.Barrier(2)

    class Slow(FakeModelProvider):
        def generate(self, request: ModelRequest) -> ModelResponse:
            sent.append(request.model_id)
            return super().generate(request)

    def worker() -> None:
        conn = open_store(world.path, world.clock)
        try:
            client = BudgetedModelClient(
                conn,
                world.clock,
                ModelRouter(CATALOG[:1], Consent({"openai"})),
                {"openai": Slow("openai")},
                SPEC_REFERENCE_TABLE,
                BudgetManager(conn, world.clock, limits),
            )
            gate.wait()
            client.call(task_id=task_id, req=Requirements(), request=REQ)
        except BudgetError:
            errors.append("budget")
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sent) == 1 and errors == ["budget"]


def test_unknown_attempts_expire_conservatively_after_retention(world: World, task_id: str) -> None:
    p = ScriptedProvider("openai", [ProviderCallError("read timeout", sent=None), "ok"])
    client = make(world, {"openai": p})
    client.call(task_id=task_id, req=Requirements(), request=REQ)
    assert client.expire_unknown() == []  # still inside the window
    world.clock.advance(days=8)
    expired = client.expire_unknown()
    assert len(expired) == 1
    row = world.conn.execute(
        "SELECT b.status, b.amount_minor, b.settled_minor FROM inference_attempts a"
        " JOIN budget_reservations b ON b.id = a.reservation_id WHERE a.id = ?",
        (expired[0],),
    ).fetchone()
    assert (
        row["status"] == "SETTLED" and row["settled_minor"] == row["amount_minor"]
    )  # never released blindly


def test_resolution_requires_evidence_and_authority(world: World, task_id: str) -> None:
    p = ScriptedProvider("openai", [ProviderCallError("read timeout", sent=None), "ok"])
    client = make(world, {"openai": p})
    client.call(task_id=task_id, req=Requirements(), request=REQ)
    attempt = world.conn.execute("SELECT id FROM inference_attempts WHERE status='UNKNOWN'").fetchone()[0]
    with pytest.raises(AtlasError):
        client.resolve_attempt(attempt, actor=Actor("runtime", "rt"), charged=None, evidence="acho que nao")
    with pytest.raises(AtlasError):
        client.resolve_attempt(attempt, actor=world.owner, charged=None, evidence=" ")
    client.resolve_attempt(
        attempt, actor=world.owner, charged=None, evidence="exportacao de uso sintetica sem esta requisicao"
    )
    assert attempts(world)[0] == ("RESOLVED", "RELEASED")
