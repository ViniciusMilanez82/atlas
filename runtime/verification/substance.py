"""Substance of a deliverable (R5-05, spec 13.3): does it do what was asked, with correct numbers?

Keyword presence is only an auxiliary signal. These deterministic checks look at the structure the
request calls for and at the numbers the deliverable states:

* denial - a deliverable that says it did not do the work ("não comparei", "não foram verificadas")
  is never a complete delivery, whatever words it contains;
* expected structure, derived from the FULL request - a comparison presents at least two options with
  values; a recommendation is actually made (not negated); a calculation shows a total that code can
  recompute;
* labelled totals - in prose, tables or spreadsheet cells, a "total" must equal the sum of the
  labelled components before it (subtotal, frete, impostos, taxas, seguro, minus descontos);
* objective - "menor preço" / "menor prazo": the recommended option must be the cheapest / fastest of
  the options the deliverable itself lists (an inverted criterion fails).

When code cannot prove a property it says so; absence of a recognised calculation is never reported
as a verified calculation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from runtime.verification.conditions import fold

_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_CELL_REF = re.compile(r"\b[A-Z]{1,3}\d+=")
_COMPONENT = r"subtotal|sub-total|frete|impostos?|tributos?|taxas?|seguro|descontos?|acrescimos?|juros|servicos?"
LABELLED = re.compile(
    r"\b(?P<label>" + _COMPONENT + r"|total)\b[^0-9\n]{0,25}?(?:r\$|us\$|usd|brl|eur|€)?\s?" + _NUM
)
_MONEY = re.compile(r"(?:r\$|us\$|usd|brl|eur|€)\s?" + _NUM)
_DAYS = re.compile(r"\b(\d+)\s*(?:dias?|dia util|dias uteis)\b")
_DENIAL = re.compile(
    r"\bnao\s+(?:comparei|comparamos|fiz|fizemos|realizei|realizamos|analisei|analisamos|verifiquei|"
    r"verificamos|calculei|calculamos|recomendei|recomendamos|li|lemos|consegui|conseguimos|pesquisei|"
    r"elaborei|consultei)\b"
    r"|\bnao\s+(?:foi|foram)\s+(?:feit|realizad|comparad|verificad|analisad|calculad|consultad|lid)\w*"
    r"|\bnenhuma?\s+(?:opcao|comparacao|recomendacao|analise|verificacao)\s+(?:foi|foram)\b"
)
_RECOMMEND = re.compile(
    r"\b(recomendo|recomendamos|recomendacao|recomendado|sugiro|sugerimos|indico|indicamos|a melhor opcao|"
    r"melhor escolha|opte por|escolha|escolher|contrate|contratar|vencedor)\b"
)
_NEGATED = re.compile(r"\bnao\s+(?:\w+\s+){0,2}(?:recomend|sugir|sugiro|indic|escolh|fiz)")
_OPTION = re.compile(r"\b(?:fornecedor|fornecedora|opcao|proposta|empresa|plano|modelo|loja)\s+([a-z0-9][\w-]{0,30})")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_PART = re.compile(r"\b(limitac\w*|pagina|trecho|parte|secao|anexo|item|planilha|aba)\b")
_OUT = re.compile(r"fora do (?:limite|prazo|teto)|acima do (?:limite|teto)|descart|nao atende|exced|exclu")


def to_decimal(raw: str) -> Decimal | None:
    try:
        if re.fullmatch(r"\d+\.\d{1,2}", raw):  # spreadsheet float "100.5"
            return Decimal(raw)
        return Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def normalize(body: str) -> str:
    """Folded text with spreadsheet cell references removed ("A2='Frete'; B2=20" -> "'frete'; 20")."""
    return fold(_CELL_REF.sub("", body))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n+", text) if s.strip()]


@dataclass
class Expectations:
    comparison: bool = False
    recommendation: bool = False
    calculation: bool = False
    objective: str | None = None  # "min_price" | "min_deadline"
    max_days: int | None = None  # "prazo máximo de 5 dias": options above it do not compete

    def as_params(self) -> dict[str, object]:
        return {
            "comparison": self.comparison,
            "recommendation": self.recommendation,
            "calculation": self.calculation,
            "objective": self.objective,
            "max_days": self.max_days,
        }

    def any(self) -> bool:
        return self.comparison or self.recommendation or self.calculation


def expectations(request: str) -> Expectations:
    f = fold(request)
    exp = Expectations(
        comparison=bool(re.search(r"\bcompar\w*|\bversus\b|\bentre as (?:opcoes|propostas)|\bqual (?:e )?(?:a )?melhor", f)),
        recommendation=bool(re.search(r"\brecomend\w*|\bsugir\w*|\bsugest\w*|\bindique (?:a|o) melhor|\bqual escolher", f)),
        # "no total" inside a cap is not a request to compute; "incluindo ... total" or "calcule" is
        calculation=bool(
            re.search(
                r"\bcalcul\w*|\borcamento\b|\bsom[ae] (?:os|as|o|a)\b|\bquanto (?:custa|fica)"
                r"|\b(?:inclua|incluindo|com|apresente|mostre|informe)\b[^.;]{0,40}\btotal\b",
                f,
            )
        ),
    )
    if re.search(r"menor (?:preco|custo|valor)|mais barat|mais em conta", f):
        exp.objective = "min_price"
    elif re.search(r"menor prazo|mais rapid\w*|entrega mais cedo", f):
        exp.objective = "min_deadline"
    limit = re.search(r"(?:prazo maximo|no maximo|em ate|ate)\D{0,30}?(\d+)\s*dias?", f)
    if limit:
        exp.max_days = int(limit.group(1))
    return exp


@dataclass
class Substance:
    gaps: list[str] = field(default_factory=list)
    structure_ok: bool = False  # the expected structure is present (used to accept paraphrases)
    totals_checked: int = 0
    totals_wrong: list[str] = field(default_factory=list)


_CAP_CONTEXT = re.compile(r"(teto|limite|maximo|ate|orcamento de|nao ultrapass\w*)\W*(?:de\s+)?$")
_UNIT_CONTEXT = re.compile(r"unitari|por unidade|\bcada\b|/mes|mensal|por mes|/ano|anual|por dia")


def check_totals(body: str) -> tuple[int, list[str]]:
    """Every labelled total must equal the components stated since the previous total: labelled ones
    (subtotal, frete, impostos, taxas, seguro, minus descontos) and plain amounts of the same block.
    Caps are not components; a block with unit prices or recurring amounts is not provable by a sum
    and is left unchecked (never reported as verified)."""
    norm = normalize(body)
    events: list[tuple[int, str, Decimal]] = []
    spans: list[tuple[int, int]] = []
    for m in LABELLED.finditer(norm):
        value = to_decimal(m.group(2))
        if value is not None:
            events.append((m.start(), m.group("label"), value))
            spans.append((m.start(), m.end()))
    for m in _MONEY.finditer(norm):
        if any(a <= m.start() < b for a, b in spans):
            continue
        value = to_decimal(m.group(1))
        if value is None:
            continue
        before, after = norm[max(0, m.start() - 30): m.start()], norm[m.end(): m.end() + 15]
        if _CAP_CONTEXT.search(before):
            continue
        events.append((m.start(), "unit" if _UNIT_CONTEXT.search(before + " " + after) else "valor", value))
    checked, wrong = 0, []
    components: list[tuple[str, Decimal]] = []
    for _, label, value in sorted(events, key=lambda e: e[0]):
        if label != "total":
            components.append((label, value))
            continue
        if components and not any(lbl == "unit" for lbl, _ in components):
            expected = sum((-v if lbl.startswith("desconto") else v) for lbl, v in components)
            checked += 1
            if abs(expected - value) > Decimal("0.01"):
                parts = " + ".join(f"{lbl} {v}" for lbl, v in components)
                wrong.append(f"total {value} não confere com {parts} = {expected}")
        components = []
    return checked, wrong


def _options(body: str) -> dict[str, tuple[Decimal | None, int | None, str]]:
    """Options the deliverable lists, with the total/price and deadline stated next to them."""
    out: dict[str, tuple[Decimal | None, int | None, str]] = {}
    for s in sentences(normalize(body)):
        names = _OPTION.findall(s)
        if len(names) != 1 or _RECOMMEND.search(s):
            continue
        totals = [to_decimal(m.group(2)) for m in LABELLED.finditer(s) if m.group("label") == "total"]
        money = totals or [to_decimal(m.group(1)) for m in _MONEY.finditer(s)]
        days = [int(d) for d in _DAYS.findall(s)]
        price = next((v for v in money if v is not None), None)
        if price is not None or days:
            prev = out.get(names[0])
            out[names[0]] = (price if price is not None else (prev[0] if prev else None),
                             days[0] if days else (prev[1] if prev else None), s)
    return out


def _recommended(body: str, options: dict[str, tuple[Decimal | None, int | None, str]]) -> str | None:
    for s in sentences(normalize(body)):
        if _RECOMMEND.search(s) and not _NEGATED.search(s):
            named = [str(n) for n in _OPTION.findall(s) if n in options]
            if named:
                return named[0]
    return None


def check_substance(body: str, exp: Expectations) -> Substance:
    res = Substance()
    norm = normalize(body)
    for s in sentences(norm):
        if _DENIAL.search(s) and not _PART.search(s):  # a stated limitation of one part is honest, not denial
            res.gaps.append(f"a entrega declara que o trabalho não foi feito: «{s[:120]}»")
            break
    structure = True
    if exp.comparison:
        values = {m.group(1) for m in _MONEY.finditer(norm)} | {d for d in _DAYS.findall(norm)}
        rows = len(_TABLE_ROW.findall(body))
        if len(values) < 2 and rows < 3:
            structure = False
            res.gaps.append("não apresenta uma comparação: faltam ao menos duas opções com valores")
    if exp.recommendation:
        rec = [s for s in sentences(norm) if _RECOMMEND.search(s) and not _NEGATED.search(s)]
        if not rec:
            structure = False
            res.gaps.append("não faz a recomendação pedida")
    res.totals_checked, res.totals_wrong = check_totals(body)
    if exp.calculation and res.totals_checked == 0:
        structure = False
        res.gaps.append(
            "cálculo não verificável: apresente os componentes (subtotal, frete, impostos...) e o total"
        )
    if exp.objective:
        options = _options(body)
        chosen = _recommended(body, options)
        idx = 0 if exp.objective == "min_price" else 1
        ranked = {
            n: v[idx]
            for n, v in options.items()
            if v[idx] is not None
            and not _OUT.search(v[2])  # the deliverable itself discarded it (over a limit, excluded)
            and not (exp.max_days is not None and v[1] is not None and v[1] > exp.max_days)
        }
        if chosen is not None and chosen in ranked and len(ranked) >= 2:
            best = min(ranked.values())  # type: ignore[type-var]
            if ranked[chosen] != best:
                what = "menor preço" if idx == 0 else "menor prazo"
                res.gaps.append(
                    f"a recomendação contraria o critério pedido ({what}): «{chosen}» não é a melhor opção listada"
                )
    res.structure_ok = structure and exp.any()
    return res
