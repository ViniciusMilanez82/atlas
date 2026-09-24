"""N11 / spec 14.3: real PDF, DOCX, XLSX and PPTX deliverables, validated by re-reading before storage.

Controlled FAKE model drives the real tool path (broker -> builtin adapter -> artifact store -> verifier).
Files are then opened again by the format extractors (the same used for inputs).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from runtime.documents.extract import extract
from runtime.documents.generate import GenerationError, generate
from runtime.verification.criteria import derive_criteria
from runtime.verification.verifier import DeliverableSpec
from tests.conftest import World
from tests.integration.test_agent_loop import UUID, build, decision

BLOCKS: list[dict[str, Any]] = [
    {"type": "heading", "text": "Comparação dos fornecedores"},
    {
        "type": "paragraph",
        "text": "O fornecedor Alfa entrega em 10 dias; o Beta, em 25 dias. Preço mensal: ação de "
        "redução de 1.000 - 900 = 100.",
    },
    {"type": "bullets", "items": ["Alfa: prazo menor", "Beta: preço menor"]},
    {
        "type": "table",
        "sheet": "Resumo",
        "rows": [["Fornecedor", "Preço", "Prazo"], ["Alfa", 1000, 10], ["Beta", 900, 25]],
    },
    {"type": "slide", "title": "Recomendação", "bullets": ["Escolher Alfa quando o prazo importa"]},
]


@pytest.mark.parametrize("ext", [".pdf", ".docx", ".xlsx", ".pptx"])
def test_each_format_round_trips(ext: str) -> None:
    g = generate(f"relatorio{ext}", "Relatório de propostas", BLOCKS)
    ex = extract(g.data, f"relatorio{ext}")
    text = " ".join(s.text for s in ex.segments)
    assert ex.state == "READY_FOR_ANALYSIS"
    assert "Alfa" in text and "Beta" in text and "1000" in text.replace(".", "")
    if ext != ".xlsx":
        assert "Comparação dos fornecedores" in " ".join(text.split())  # accents survive (WinAnsi in PDF)


def test_invalid_requests_never_produce_a_file() -> None:
    with pytest.raises(GenerationError):
        generate("relatorio.odt", "x", BLOCKS)
    with pytest.raises(GenerationError):
        generate("relatorio.pdf", "x", [])


def test_agent_delivers_a_verified_docx(world: World, tmp_path: Path) -> None:
    objective = "Compare as propostas dos fornecedores Alfa e Beta e entregue um documento Word"

    def policy(turn: int, prompt: str) -> str:
        ids = re.findall(rf"artifact_id ({UUID})", prompt)
        if turn == 1:
            return decision("tool", tool="documents.read", inp={"artifact_id": ids[0], "cursor": 0})
        if turn == 2:
            blocks = [*BLOCKS, {"type": "paragraph", "text": f"Fonte: artifact:{ids[0]}"}]
            return decision(
                "tool",
                tool="artifact.write_document",
                inp={"name": "comparacao.docx", "title": "Propostas", "blocks": blocks},
            )
        written = re.findall(rf'"artifact_id": "({UUID})", "name": "comparacao.docx"', prompt)
        return decision("finish", artifact=written[-1])

    s = build(world, tmp_path, policy)
    s.runner.catalog = s.runner._catalog([*s.runner.tools, "artifact.write_document"])
    tid = s.tasks.create(
        world.owner,
        employee_id=world.employee.id,
        objective=objective,
        criteria=[(c.description, c.required, c.kind, c.params) for c in derive_criteria(objective, True)],
    )
    f = tmp_path / "propostas.txt"
    f.write_text(
        "Fornecedor Alfa: 1.000 por mes, 10 dias. Fornecedor Beta: 900 por mes, 25 dias.", encoding="utf-8"
    )
    s.am.import_file(f, actor=world.owner, employee_id=world.employee.id, task_id=tid)
    out = s.runner.run(tid, DeliverableSpec(min_chars=100))
    assert out.state == "COMPLETED", (out.reason, out.gaps)
    art = s.am.get(out.deliverable_id or "")
    assert art.mime_type.endswith("wordprocessingml.document") and art.name == "comparacao.docx"
    assert extract(s.am.read_bytes(art.id), art.name).state == "READY_FOR_ANALYSIS"
