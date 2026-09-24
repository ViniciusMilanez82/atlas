"""A3-07 (a valid file does not prove the objective) and A3-08 (Portuguese "todo" is not a placeholder)
- scenario T23.

Each false delivery goes through the SAME verifier and loop used before COMPLETED: wrong subject, wrong
calculation, a source that was never retrieved, an input document not read to the end. None may finish
as COMPLETED; the gaps are specific per criterion. A legitimate Portuguese report passes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from runtime.verification.criteria import derive_criteria
from runtime.verification.verifier import PLACEHOLDERS
from tests.conftest import World
from tests.integration.test_agent_loop import SPEC, UUID, build, decision

OBJECTIVE = "Compare as propostas dos fornecedores Alfa e Beta e recomende a melhor"
DOC_A = "Proposta do fornecedor Alfa: R$ 1.000 por mes, entrega em 10 dias."
DOC_B = (
    "Proposta do fornecedor Beta: R$ 900 por mes, entrega em 25 dias. "
    + "Detalhe tecnico. " * 900
    + ("Clausula final: multa de 30% em caso de atraso.")
)


def good_report(ids: list[str]) -> str:
    return (
        "# Comparacao das propostas\n\nTodo o conteudo foi analisado. O fornecedor Alfa cobra R$ 1.000 por mes e o "
        "fornecedor Beta cobra R$ 900 por mes: diferenca de 1.000 - 900 = 100 por mes. O Beta tem multa de 30% por "
        "atraso.\n\nRecomendacao: fornecedor Alfa, pelo prazo e sem multa.\n\n"
        f"Fontes: artifact:{ids[0]} e artifact:{ids[1]}\n"
    )


def _run(world: World, tmp_path: Path, writer: Any, read_all: bool = True) -> tuple[Any, Any, str]:
    state: dict[str, Any] = {}

    def policy(turn: int, prompt: str) -> str:
        ids = state.setdefault("ids", re.findall(rf"artifact_id ({UUID})", prompt))
        cursors = re.findall(r'"next_cursor": (\d+)', prompt)
        if turn == 1:
            return decision("tool", tool="documents.read", inp={"artifact_id": ids[0], "cursor": 0})
        if turn == 2:
            return decision("tool", tool="documents.read", inp={"artifact_id": ids[1], "cursor": 0})
        if read_all and cursors and not state.get("done"):
            nxt = int(cursors[-1])
            if '"has_more": false' in prompt.split("EXTERNAL-DATA")[-1]:
                state["done"] = True
            else:
                return decision("tool", tool="documents.read", inp={"artifact_id": ids[1], "cursor": nxt})
        if not state.get("written"):
            state["written"] = True
            return decision(
                "tool", tool="artifact.write_text", inp={"name": "relatorio.md", "content": writer(ids)}
            )
        written = re.findall(rf'"artifact_id": "({UUID})", "name": "relatorio.md"', prompt)
        return decision("finish", artifact=written[-1])

    s = build(world, tmp_path, policy)
    tid = s.tasks.create(
        world.owner,
        employee_id=world.employee.id,
        objective=OBJECTIVE,
        criteria=[(c.description, c.required, c.kind, c.params) for c in derive_criteria(OBJECTIVE, True)],
    )
    for name, text in (("alfa.txt", DOC_A), ("beta.txt", DOC_B)):
        f = tmp_path / name
        f.write_text(text, encoding="utf-8")
        s.am.import_file(f, actor=world.owner, employee_id=world.employee.id, task_id=tid)
    out = s.runner.run(tid, SPEC)
    gaps = " ".join(out.gaps) + " " + " ".join(s.model.prompts[-1:])
    return s, out, gaps


def test_legitimate_portuguese_report_completes(world: World, tmp_path: Path) -> None:
    _, out, _ = _run(world, tmp_path, good_report)
    assert out.state == "COMPLETED", (out.reason, out.gaps)
    ev = world.conn.execute(
        "SELECT COUNT(DISTINCT evidence_id) FROM task_criteria WHERE task_id = ? AND satisfied_at IS NOT NULL",
        (out.task_id,),
    ).fetchone()[0]
    assert ev >= 4  # one evidence per criterion, not one generic "file opens" for all


@pytest.mark.parametrize(
    ("label", "writer", "read_all", "gap"),
    [
        (
            "wrong subject",
            lambda ids: (
                "# Receita de bolo\n\n"
                + "Misture farinha e ovos. " * 20
                + f"\nFontes: artifact:{ids[0]} artifact:{ids[1]}"
            ),
            True,
            "pedido",
        ),
        ("wrong calculation", lambda ids: good_report(ids).replace("= 100", "= 250"), True, "cálculo"),
        (
            "invented source",
            lambda ids: good_report(ids) + "\nVer tambem https://exemplo-inventado.test/tabela\n",
            True,
            "fonte",
        ),
        (
            "unknown artifact",
            lambda ids: good_report(ids).replace(ids[1], "00000000-0000-4000-8000-000000000000"),
            True,
            "fonte",
        ),
        ("final clause never read", good_report, False, "lido"),
    ],
)
def test_false_deliveries_never_complete(
    world: World, tmp_path: Path, label: str, writer: Any, read_all: bool, gap: str
) -> None:
    _, out, gaps = _run(world, tmp_path, writer, read_all)
    assert out.state != "COMPLETED", f"{label}: completed with a false delivery"  # before the fix: COMPLETED
    assert gap in gaps.lower(), f"{label}: gap not explained: {gaps[:400]}"


@pytest.mark.parametrize(
    "text",
    [
        "Todo o trabalho foi concluído.",
        "Verifique todo o orçamento.",
        "todos os itens",
        "Para todo mês há uma meta.",
    ],
)
def test_portuguese_todo_is_not_a_placeholder(text: str) -> None:
    assert not PLACEHOLDERS.search(text)  # before the fix: (?i)\bTODO\b matched


@pytest.mark.parametrize(
    "text",
    [
        "TODO: completar a tabela",
        "Valor: [inserir valor]",
        "{{nome_do_cliente}}",
        "Lorem ipsum dolor",
        "FIXME revisar",
        "Resultado: TBD",
    ],
)
def test_real_placeholders_are_still_caught(text: str) -> None:
    assert PLACEHOLDERS.search(text)
