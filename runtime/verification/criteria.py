"""Completion criteria derived from the owner's request (A3-07, spec 13.1/13.3).

A task is not "done" because a file opens. Each criterion names one property with its own deterministic
check and its own evidence: integrity, coverage of the request, arithmetic stated in the text, sources
really retrieved in this task, and complete reading of the input documents. Criteria are derived from the
request by code (never by the model) and stored with the task; the owner may waive one explicitly later.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

KINDS = ("integrity", "coverage", "calculations", "sources", "inputs_read", "required_terms", "condition")
# Conditions code can check deterministically block completion; the others are reported as limitations
# of the automatic verification instead of being silently "verified" (R5-05).
CHECKED_CONDITIONS = ("DATE", "MONEY_CAP", "EXCLUSION", "SEPARATE")
_STOP = frozenset(
    "a o as os um uma uns umas de da do das dos e em no na nos nas para por com sem que se ao aos qual quais "
    "meu minha meus minhas seu sua seus suas este esta estes estas esse essa isso isto sobre entre como mais "
    "menos muito pouco todo toda todos todas cada anexo anexos anexa anexas arquivo arquivos documento "
    "documentos relatorio relatorios texto resumo planilha tabela duas dois tres quatro cinco entrega".split()
)
_VERBS = frozenset(
    "compare comparar compara analise analisar analisa faca fazer crie criar gere gerar entregue entregar "
    "recomende recomendar resuma resumir escreva escrever prepare preparar monte montar elabore elaborar "
    "revise revisar verifique verificar pesquise pesquisar procure procurar calcule calcular organize "
    "organizar liste listar mande mandar envie enviar traduza traduzir explique explicar diga dizer "
    "indique indicar mostre mostrar produza produzir redija redigir leia ler use usar priorize priorizar "
    "considere considerar inclua incluir mude mudar troque trocar substitua substituir abandone abandonar "
    "apresente apresentar mantenha manter".split()
)


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def stem(word: str) -> str:
    return word[:5] if len(word) > 5 else word


def key_terms(request: str, limit: int = 8) -> list[str]:
    """Significant words of the request (stems), in order, without verbs and stopwords."""
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", fold(request)):
        if len(w) < 4 or w in _STOP or w in _VERBS:
            continue
        s = stem(w)
        if s not in out:
            out.append(s)
    return out[:limit]


@dataclass(frozen=True)
class Criterion:
    description: str
    required: bool
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


def derive_criteria(request: str, has_inputs: bool) -> list[Criterion]:
    terms = key_terms(request)
    crit = [
        Criterion("Arquivo de entrega íntegro, legível e sem marcadores pendentes", True, "integrity"),
        Criterion(
            "Atende ao pedido (aborda: " + ", ".join(terms) + ")" if terms else "Atende ao pedido",
            True,
            "coverage",
            {"terms": terms, "min_ratio": 0.5},
        ),
        Criterion("Cálculos apresentados conferem", True, "calculations"),
        Criterion(
            "Fontes citadas existem e foram consultadas nesta tarefa",
            True,
            "sources",
            {"min": 1 if has_inputs else 0},
        ),
    ]
    if has_inputs:
        crit.append(Criterion("Documentos de entrada lidos por completo", True, "inputs_read"))
    from runtime.verification.conditions import extract_conditions

    for cond in extract_conditions(request):  # each mapped to the owner's sentence (R5-02)
        crit.append(Criterion(cond.describe(), cond.kind in CHECKED_CONDITIONS, "condition", cond.as_params()))
    quoted = re.findall(r"[\"“«]([^\"”»]{3,120})[\"”»]", request)
    if quoted:
        crit.append(
            Criterion("Inclui o que foi pedido entre aspas", True, "required_terms", {"terms": quoted})
        )
    return crit
