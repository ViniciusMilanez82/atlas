"""Conditions of the owner's request, each mapped to the exact passage it came from (R5-02, R5-05).

Extraction is deterministic and conservative: it never deletes a restriction, it only makes explicit
the ones code can recognise (dates, monetary caps, exclusions, items to present separately, quantities
and priorities). Every condition keeps its source sentence, so a summary produced by a model can never
replace it, and the verifier checks each one against the deliverable (R5-05). Anything not recognised
here still reaches the model verbatim through the ORIGINAL instruction revision.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+|\n+")  # "R$ 8.000" is not the end of a sentence
DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
MONEY = re.compile(r"(R\$|US\$|USD|BRL|EUR|€)\s?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)", re.IGNORECASE)
_CAP = re.compile(r"\b(nao ultrapass\w*|ate|no maximo|maximo|teto|limite|nao pass\w*|nao exced\w*|abaixo de)\b")
_EXCLUDE = re.compile(
    r"\b(exclua|excluir|excluindo|exceto|nao inclua|nao incluir|nao considere|desconsidere|ignore|evite|"
    r"sem|nunca|nao use|nao usar|proibido|abandone|esqueca|deixe de lado|em vez de|ao inves de)\b\s+(?P<obj>[^,.;]{3,120}?)"
    r"(?=\s+e\s+|[,.;]|$)"  # the object ends at the next clause: "abandone as macas e produza..."
)
_SEPARATE_AFTER = re.compile(r"\s+(?:separadamente|em separado|a parte|discriminad\w*)\b")
_SEPARATE_BEFORE = re.compile(r"\b(?:separe|discrimine|destaque)\s+(?P<obj>[^,.;]{3,80})")
_CLAUSE = re.compile(r",|;|\be\b|\bmas\b")
QUANTITY = re.compile(r"\b(\d+)\s*(dias?|horas?|semanas?|meses|anos?|paginas?|itens|opcoes|fornecedores)\b")
_PRIORITY = re.compile(r"\b(priorize|prioridade|priorizar|primeiro|antes de tudo|mais importante)\b")
_VERB_LEAD = re.compile(r"^(?:e\s+)?(?:apresente|mostre|informe|liste|indique|traga|coloque|inclua)\s+")


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def money_value(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class Condition:
    kind: str  # DATE | MONEY_CAP | EXCLUSION | SEPARATE | QUANTITY | PRIORITY
    span: str  # the owner's sentence, verbatim
    value: str  # normalised value the verifier looks for

    def describe(self) -> str:
        labels = {
            "DATE": "Respeita a data",
            "MONEY_CAP": "Respeita o teto",
            "EXCLUSION": "Respeita a exclusão",
            "SEPARATE": "Apresenta separadamente",
            "QUANTITY": "Respeita a quantidade",
            "PRIORITY": "Respeita a prioridade",
        }
        return f"{labels[self.kind]}: «{self.span[:160]}»"

    def as_params(self) -> dict[str, str]:
        return {"kind": self.kind, "span": self.span, "value": self.value}


def extract_conditions(request: str) -> list[Condition]:
    out: list[Condition] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, span: str, value: str) -> None:
        key = (kind, fold(value).strip())
        if key not in seen and value.strip():
            seen.add(key)
            out.append(Condition(kind, span.strip(), value.strip()))

    for raw in _SENTENCE_END.split(request):
        sentence = raw.strip()
        if not sentence:
            continue
        folded = fold(sentence)
        for d in DATE.finditer(sentence):
            add("DATE", sentence, d.group(0))
        for mo in MONEY.finditer(sentence):
            if _CAP.search(fold(sentence[: mo.start()])[-40:]):
                add("MONEY_CAP", sentence, mo.group(2))
        for ex in _EXCLUDE.finditer(folded):
            add("EXCLUSION", sentence, ex.group("obj"))
        for sp in _SEPARATE_AFTER.finditer(folded):  # "... e apresente os impostos separadamente"
            clause = _CLAUSE.split(folded[: sp.start()])[-1].strip()
            add("SEPARATE", sentence, _VERB_LEAD.sub("", clause))
        for sp in _SEPARATE_BEFORE.finditer(folded):  # "discrimine o frete"
            add("SEPARATE", sentence, sp.group("obj"))
        for q in QUANTITY.finditer(folded):
            add("QUANTITY", sentence, q.group(0))
        if _PRIORITY.search(folded):
            add("PRIORITY", sentence, sentence)
    return out
