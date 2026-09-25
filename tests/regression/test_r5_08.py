"""R5-08 (P2; reopens A3-07/A3-26): a registered URL is not a retrieved source. Only a retrieval
recorded for THIS task (or an explicitly authorized reuse of a capture of the same employee), still
valid, whose captured content backs the claim, validates a citation. No network is used: the
retrieval is recorded as the research adapter will record it (N16).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.memory.manager import MemoryManager
from runtime.verification.verifier import DeliverableSpec
from shared.actors import Actor
from shared.errors import AtlasError
from storage.repositories.identity import create_employee, create_owner
from tests.regression.r5_harness import R5World

URL = "https://source.example.invalid/precos"
CAPTURE = "Tabela de preços 2026: o módulo solar custa R$ 1.250,00 e a garantia é de 12 anos."


def _gap(r5: R5World, tid: str, body: str) -> str | None:
    return r5.verifier._sources(tid, body, 1, DeliverableSpec())


def _retrieve(r5: R5World, tid: str, **kw: object) -> str:
    from runtime.research.sources import SourceRetrievals  # local: the pre-fix code has no such module

    return SourceRetrievals(r5.conn, r5.clock, r5.artifacts).record_retrieval(
        task_id=tid, url=URL, final_url=URL, content=CAPTURE, adapter="test-adapter",
        receipt={"status": 200, "bytes": len(CAPTURE)}, **kw,  # type: ignore[arg-type]
    )


def test_registered_url_of_another_owner_is_not_a_source(r5: R5World) -> None:
    """The reviewer's case: a web source registered for another owner/employee validated this task."""
    tid = r5.create("Relatório de teste sobre fornecedores.")
    other_owner = create_owner(r5.conn, r5.clock, "Other synthetic owner")
    other = create_employee(r5.conn, r5.clock, owner_id=other_owner, name="Other")
    MemoryManager(r5.conn, r5.clock).add_source(
        actor=Actor("owner", other_owner, "local_app"), kind="web", ref=URL, employee_id=other.id
    )
    assert _gap(r5, tid, f"O módulo custa R$ 1.250,00. Fonte: {URL}") is not None


def test_registered_but_never_retrieved_url_of_this_employee_fails(r5: R5World) -> None:
    tid = r5.create("Relatório de teste sobre fornecedores.")
    MemoryManager(r5.conn, r5.clock).add_source(actor=r5.owner, kind="web", ref=URL, employee_id=r5.emp.id)
    assert "não foi recuperada" in (_gap(r5, tid, f"O módulo custa R$ 1.250,00. Fonte: {URL}") or "")


def test_retrieved_in_this_task_and_backing_the_claim_passes(r5: R5World) -> None:
    tid = r5.create("Relatório de teste sobre fornecedores.")
    _retrieve(r5, tid)
    assert _gap(r5, tid, f"O módulo solar custa R$ 1.250,00. Fonte: {URL}.") is None
    assert _gap(r5, tid, f"A garantia do módulo é de 12 anos ({URL}).") is None


def test_citation_that_does_not_support_the_claim_fails(r5: R5World) -> None:
    tid = r5.create("Relatório de teste sobre fornecedores.")
    _retrieve(r5, tid)
    gap = _gap(r5, tid, f"O módulo solar custa R$ 990,00. Fonte: {URL}")
    assert gap is not None and "não sustenta" in gap


def test_capture_of_another_task_needs_explicit_reuse_and_other_employee_never(r5: R5World) -> None:
    first = r5.create("Pesquisa de preços de módulos.")
    rid = _retrieve(r5, first)
    second = r5.create("Relatório de teste sobre fornecedores.")
    body = f"O módulo solar custa R$ 1.250,00. Fonte: {URL}"
    assert _gap(r5, second, body) is not None  # not consulted in THIS task
    from runtime.research.sources import SourceRetrievals

    retrievals = SourceRetrievals(r5.conn, r5.clock, r5.artifacts)
    with pytest.raises(AtlasError):
        retrievals.authorize_reuse(task_id=second, retrieval_id=rid, actor=Actor("runtime", "x", "internal"))
    retrievals.authorize_reuse(task_id=second, retrieval_id=rid, actor=r5.owner)
    assert _gap(r5, second, body) is None  # stable data reused with a recorded authorization
    other_owner = create_owner(r5.conn, r5.clock, "Other")
    other = create_employee(r5.conn, r5.clock, owner_id=other_owner, name="Other")
    foreign = r5.tasks.create(Actor("owner", other_owner, "local_app"), employee_id=other.id, objective="x")
    with pytest.raises(AtlasError):
        retrievals.authorize_reuse(task_id=foreign, retrieval_id=rid, actor=Actor("owner", other_owner, "local_app"))


def test_expired_retrieval_for_a_time_sensitive_fact_fails(r5: R5World) -> None:
    tid = r5.create("Relatório de teste sobre fornecedores.")
    _retrieve(r5, tid, valid_for=timedelta(hours=1))
    body = f"O módulo solar custa R$ 1.250,00. Fonte: {URL}"
    assert _gap(r5, tid, body) is None
    r5.clock.advance(hours=2)
    assert "expirou" in (_gap(r5, tid, body) or "")
