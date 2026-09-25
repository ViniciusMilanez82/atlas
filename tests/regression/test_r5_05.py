"""R5-05 (P1; reopens A3-07): keywords are only an auxiliary signal. A report that denies the work,
a wrong total in prose/table/spreadsheet, an omitted item, an invented reference, an excluded option
or an inverted criterion does not complete; a correct paraphrase without the literal words does.
The explicit-equation control and the integrity checks are kept.
"""

from __future__ import annotations

import io

import openpyxl
import pytest

from runtime.verification.verifier import DeliverableSpec
from tests.regression.r5_harness import CP, R5World

COMPARE = "Compare fornecedores e recomende o menor preço respeitando o prazo máximo de entrega de 5 dias."
BUDGET = "Calcule o orçamento incluindo subtotal, frete e total."
PAD = " Este documento sintético existe apenas para os testes de verificação do Atlas."


def _verify(r5: R5World, request: str, text: str, name: str = "relatorio.txt") -> tuple[bool, list[str]]:
    tid = r5.create(request)
    res = r5.verifier.verify_text_artifact(tid, r5.artifact(tid, text, name=name).id, DeliverableSpec())
    return res.passed, res.gaps


def test_report_that_denies_the_work_fails_despite_the_keywords(r5: R5World) -> None:
    text = "Fornecedores, preço, prazo, máximo e entrega são as palavras que constam neste relatório. " + (
        "Não comparei nenhuma opção e não fiz recomendação. As condições solicitadas não foram verificadas. " * 3
    )
    passed, gaps = _verify(r5, COMPARE, text)
    assert not passed
    assert any("não foi feito" in g for g in gaps)


def test_correct_paraphrase_without_the_literal_words_passes(r5: R5World) -> None:
    text = (
        "Entre as três empresas avaliadas: Empresa Alfa cobra R$ 1.200,00 e entrega em 4 dias. "
        "Empresa Beta cobra R$ 950,00 e entrega em 5 dias. Empresa Gama cobra R$ 800,00, mas entrega em "
        "9 dias, fora do limite. Sugiro contratar a empresa Beta: o valor mais baixo entre as que cumprem "
        "o limite de 5 dias." + PAD
    )
    passed, gaps = _verify(r5, COMPARE, text)
    assert passed, gaps


def test_inverted_criterion_fails(r5: R5World) -> None:
    text = (
        "Empresa Alfa cobra R$ 1.200,00 e entrega em 4 dias. Empresa Beta cobra R$ 950,00 e entrega em 5 dias. "
        "Recomendo a empresa Alfa para este pedido de fornecedores com prazo máximo." + PAD
    )
    passed, gaps = _verify(r5, COMPARE, text)
    assert not passed and any("contraria o critério" in g for g in gaps)


@pytest.mark.parametrize(
    "fmt",
    ["prose", "table", "xlsx"],
)
def test_wrong_total_fails_in_prose_table_and_spreadsheet(r5: R5World, fmt: str) -> None:
    tid = r5.create(BUDGET)
    if fmt == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        for row in (["Item", "Valor (R$)"], ["Subtotal", 100], ["Frete", 20], ["Total", 500]):
            ws.append(row)
        for _ in range(12):
            ws.append(["Observação", "Orçamento sintético incluindo subtotal, frete e total para teste."])
        buf = io.BytesIO()
        wb.save(buf)
        art = r5.artifacts.create_document(
            actor=CP,
            employee_id=r5.emp.id,
            task_id=tid,
            name="orcamento.xlsx",
            data=buf.getvalue(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        text = (
            "Orçamento: subtotal R$ 100,00; frete R$ 20,00; total R$ 500,00."
            if fmt == "prose"
            else "| Item | Valor |\n|---|---|\n| Subtotal | R$ 100,00 |\n| Frete | R$ 20,00 |\n| Total | R$ 500,00 |"
        ) + (" Este é o orçamento solicitado, incluindo o subtotal, o frete e o total informados." * 3)
        art = r5.artifact(tid, text)
    res = r5.verifier.verify_text_artifact(tid, art.id, DeliverableSpec())
    assert not res.passed
    assert any("não confere" in g for g in res.gaps), res.gaps


def test_correct_total_passes_and_the_explicit_equation_control_is_kept(r5: R5World) -> None:
    ok_text = "Orçamento: subtotal R$ 100,00; frete R$ 20,00; total R$ 120,00." + PAD * 3
    passed, gaps = _verify(r5, BUDGET, ok_text)
    assert passed, gaps
    assert r5.verifier._calculations("100 + 20 = 500") is not None
    assert r5.verifier._calculations("100 + 20 = 120") is None


def test_no_recognisable_calculation_is_not_reported_as_verified(r5: R5World) -> None:
    passed, gaps = _verify(r5, BUDGET, "O orçamento com subtotal, frete e total ficou adequado." + PAD * 3)
    assert not passed and any("não verificável" in g for g in gaps)


def test_omitted_item_invented_reference_and_excluded_option_fail(r5: R5World) -> None:
    passed, gaps = _verify(
        r5,
        "Calcule o orçamento incluindo subtotal, frete, impostos e total.",
        "Orçamento: subtotal R$ 100,00; frete R$ 20,00; total R$ 120,00." + PAD * 3,
    )
    assert not passed and any("impos" in g for g in gaps)  # taxes omitted
    passed, gaps = _verify(
        r5,
        "Escreva um relatório sobre maçãs vermelhas.",
        "Relatório sobre maçãs vermelhas. Fonte: artifact:0b7a5a1e-8f65-4c6e-9b8a-3a2d1c0e9f11." + PAD * 3,
    )
    assert not passed and any("não é um anexo" in g for g in gaps)  # invented reference
    passed, gaps = _verify(
        r5,
        "Compare fornecedores de módulos e exclua contratos renováveis.",
        "Fornecedor A: R$ 6.000,00. Fornecedor B: R$ 5.000,00 com contrato renovável. "
        "Recomendo o fornecedor B, o contrato renovável mais barato." + PAD * 2,
    )
    assert not passed and any("excluído" in g for g in gaps)
