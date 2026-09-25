"""R5-06 (P1; reopens A3-09/A3-10): a PARTIAL extraction is never a complete read. Reading every
extracted segment is not reading the document; the missing areas stay visible in state and result,
and only an explicit, recorded reduced scope accepted by the owner lets the task finish - with the
limitation stated. The long-reading positive control is kept.
"""

from __future__ import annotations

import io
import json
from typing import Any

from pypdf import PdfReader, PdfWriter

from runtime.documents.generate import generate
from runtime.documents.store import DocumentStore
from runtime.tasks.state_machine import TaskState
from runtime.verification.verifier import DeliverableSpec
from shared.clock import to_utc_str
from storage.db import transaction
from tests.regression.r5_harness import R5World, decision

REQUEST = "Analise a proposta anexa do fornecedor e resuma as condições."
REPORT = (
    "Resumo da proposta do fornecedor: preço de R$ 1.000,00 por mês e prazo de 10 dias. "
    "As condições foram resumidas a partir da proposta anexa. " * 3
)


def _pdf_with_scanned_page(r5: R5World, tid: str) -> Any:
    text = generate("proposta.pdf", "Proposta", [{"type": "paragraph", "text": "Preço R$ 1.000,00 por mês; prazo 10 dias."}])
    reader = PdfReader(io.BytesIO(text.data))
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    writer.add_blank_page(width=595, height=842)  # an image-only page: nothing extractable (the essential clause)
    buf = io.BytesIO()
    writer.write(buf)
    path = r5.root / "proposta.pdf"
    path.write_bytes(buf.getvalue())
    return r5.artifacts.import_file(path, actor=r5.owner, employee_id=r5.emp.id, task_id=tid)


def _read_all(r5: R5World, tid: str, aid: str) -> dict[str, Any]:
    ds = DocumentStore(r5.conn, r5.clock, r5.artifacts)
    ds.ensure_extracted(aid)
    cursor: int | None = 0
    while cursor is not None:
        page = ds.read(aid, task_id=tid, cursor=cursor)
        cursor = page.get("next_cursor") if page.get("has_more") else None
    return ds.coverage(tid, aid)


def test_reviewer_fixture_partial_never_passes_as_complete(r5: R5World) -> None:
    tid = r5.create("Compare propostas de fornecedores.", has_inputs=True)
    art = r5.import_text("Parte legível da proposta. Outro trecho não foi extraído.", task_id=tid)
    now = to_utc_str(r5.clock.now())
    with transaction(r5.conn):
        r5.conn.execute(
            "INSERT INTO document_extractions(artifact_id, state, extractor, extractor_version, segment_count,"
            " total_chars, warnings_json, diagnostic, created_at, missing_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (art.id, "PARTIAL", "synthetic", "1", 1, 20, '["Página essencial não foi extraída"]', None, now,
             '["página 2"]'),
        )
        r5.conn.execute("INSERT INTO document_reads VALUES (?,?,?,?)", (tid, art.id, 0, now))
    text = (
        "Comparação de propostas de fornecedores: A R$ 100,00 e B R$ 120,00. " * 3 + f" Fonte: artifact:{art.id}"
    )
    res = r5.verifier.verify_text_artifact(tid, r5.artifact(tid, text).id, DeliverableSpec())
    assert not res.passed
    assert any("PARCIAL" in g and "página 2" in g for g in res.gaps)


def test_real_pdf_with_an_unreadable_page(r5: R5World) -> None:
    tid = r5.create(REQUEST, has_inputs=True)
    doc = _pdf_with_scanned_page(r5, tid)
    cov = _read_all(r5, tid, doc.id)
    assert cov["extraction_state"] == "PARTIAL"
    assert cov["segments_complete"] and not cov["complete"]  # read everything extracted != read the document
    assert cov["missing"] == ["página 2"] and cov["units_total"] == 2
    report = r5.artifact(tid, REPORT + f" Fonte: artifact:{doc.id}")
    r5.provider.reply = decision("finish", artifact_id=report.id)
    out = r5.runner.run(tid, DeliverableSpec())
    assert out.state != TaskState.COMPLETED
    assert any("PARCIAL" in g for g in out.gaps)
    notice = r5.conn.execute(
        "SELECT content FROM notification_outbox WHERE task_id = ? ORDER BY rowid DESC LIMIT 1", (tid,)
    ).fetchone()[0]
    assert "página 2" in notice  # the limitation reaches the owner, not only the log


def test_owner_accepts_reduced_scope_and_the_limitation_is_stated(r5: R5World) -> None:
    tid = r5.create(REQUEST, has_inputs=True)
    doc = _pdf_with_scanned_page(r5, tid)
    _read_all(r5, tid, doc.id)
    rev = r5.tasks.accept_reduced_scope(tid, doc.id, actor=r5.owner, note="a página 2 é só a assinatura")
    assert rev == 2
    row = r5.conn.execute(
        "SELECT instruction_revision, missing_json FROM input_scope_acceptances WHERE task_id = ?", (tid,)
    ).fetchone()
    assert row[0] == 2 and json.loads(row[1]) == ["página 2"]
    assert "não analisado: página 2" in r5.tasks.instructions(tid)[-1]["instruction"]
    silent = r5.artifact(tid, REPORT + f" Fonte: artifact:{doc.id}", name="silencioso.txt")
    res = r5.verifier.verify_text_artifact(tid, silent.id, DeliverableSpec())
    assert not res.passed and any("precisa declarar" in g for g in res.gaps)
    honest = r5.artifact(
        tid, REPORT + f" Limitação: a página 2 não foi analisada (extração parcial). Fonte: artifact:{doc.id}",
        name="honesto.txt",
    )
    r5.provider.reply = decision("finish", artifact_id=honest.id)
    out = r5.runner.run(tid, DeliverableSpec())
    assert out.state == TaskState.COMPLETED, out.gaps


def test_accept_partial_input_over_ipc_is_owner_only(env: Any, world: Any) -> None:
    from shared.actors import Actor
    from tests.integration.test_alpha2 import ok

    c = env.connect()
    rt = env.connect(actor=Actor("runtime", "rt", "internal"))
    tid = world.conn.execute("SELECT 1").fetchone()  # no task needed to prove the authority check
    resp = rt.call("tasks.accept_partial_input", task_id="00000000-0000-4000-8000-000000000000",
                   artifact_id="00000000-0000-4000-8000-000000000000")
    assert resp["error"]["data"]["atlas_code"] == "UNAUTHORIZED"
    bad = c.call("tasks.accept_partial_input", task_id="00000000-0000-4000-8000-000000000000",
                 artifact_id="00000000-0000-4000-8000-000000000000")
    assert bad["error"]["data"]["atlas_code"] == "INVALID_INPUT"
    assert tid is not None and ok is not None


def test_positive_control_long_reading_completes(r5: R5World) -> None:
    tid = r5.create("Leia a proposta inteira e compare fornecedores.", has_inputs=True)
    doc = r5.import_text("Dados sintéticos da proposta para avaliar fornecedores.\n" * 6000, name="longa.txt", task_id=tid)
    ds = DocumentStore(r5.conn, r5.clock, r5.artifacts)
    status = ds.ensure_extracted(doc.id)
    assert status["state"] == "READY_FOR_ANALYSIS"
    deliverable = r5.artifact(
        tid,
        "Comparação de fornecedores com a proposta lida integralmente. Fornecedor A: R$ 1.000,00. "
        "Fornecedor B: R$ 1.200,00. " * 3 + f" Fonte: artifact:{doc.id}",
    )

    def step(_: Any) -> dict[str, Any]:
        cur = r5.conn.execute(
            "SELECT COALESCE(MAX(seq)+1,0) FROM document_reads WHERE task_id=? AND artifact_id=?", (tid, doc.id)
        ).fetchone()[0]
        if cur >= status["segments"]:
            return decision("finish", artifact_id=deliverable.id)
        return decision("tool", tool_id="documents.read", input_json=json.dumps({"artifact_id": doc.id, "cursor": cur}))

    r5.provider.reply = step
    out = r5.runner.run(tid, DeliverableSpec())
    assert out.state == TaskState.COMPLETED and out.steps > 20, (out.reason, out.gaps)
    assert ds.coverage(tid, doc.id)["complete"]
