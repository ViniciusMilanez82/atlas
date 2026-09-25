"""Knowledge context shared by conversation and tasks (A3-01, spec 8.2; scenario T04).

One retrieval path for both: filter by employee, confirmation, tombstone/validity (via MemoryManager),
then combine
* global memories that apply regardless of the words used (confirmed IDENTITY and PREFERENCE);
* the relevant confirmed facts: when the employee has few of them, all of them (a short list is cheaper
  and safer than a ranking); otherwise a lexical search expanded with pt-BR stems and a small, curated
  table of equivalent words, ranked by bm25.
Only CONFIRMED memories are returned: a proposal is never presented as the owner's knowledge. Each item
keeps its source, validity and classification. The owner's confirmation means "informed by the owner",
not "verified by an external source", and the rendering says so.

Semantic (embedding) retrieval is a derived, rebuildable layer planned on top of this service; it is not
required for correctness and, being a disclosure when remote, will follow the same egress rules.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from runtime.memory.manager import MemoryHit, MemoryManager
from shared.clock import Clock
from shared.errors import AtlasError

SMALL_SET = 12  # up to this many confirmed facts: include them all
MAX_FACTS = 8
MAX_GLOBAL = 12
_EQUIVALENTS = [
    {"favorito", "favorita", "preferido", "preferida", "predileto", "predileta"},
    {"cachorro", "cao", "cadela", "cachorra", "pet"},
    {"gato", "gata", "felino"},
    {"chama", "chamar", "nome", "apelido"},
    {"endereco", "rua", "moro", "mora", "residencia"},
    {"telefone", "celular", "fone", "numero"},
    {"aniversario", "nascimento", "nasceu", "nasci"},
    {"filho", "filha", "filhos", "criancas", "crianca"},
    {"esposa", "esposo", "marido", "mulher", "conjuge"},
    {"empresa", "firma", "companhia", "negocio"},
    {"reuniao", "encontro", "compromisso"},
    {"preco", "valor", "custo", "orcamento"},
    {"prazo", "entrega", "data", "vencimento"},
    {"fornecedor", "fornecedores", "vendedor"},
    {"carro", "veiculo", "automovel"},
    {"medico", "doutor", "doutora", "clinica"},
]
_STOP = frozenset(
    "a o as os um uma de da do das dos e em no na nos nas para por com sem que se ao aos qual quais meu minha "
    "meus minhas seu sua como e eh esta este isso isto voce voces me te lhe the and".split()
)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def expand_terms(text: str) -> list[str]:
    """Significant words of the question, their equivalents and a 5-letter stem (prefix query)."""
    words = [w for w in re.findall(r"[a-z0-9]+", _fold(text)) if len(w) >= 3 and w not in _STOP]
    out: list[str] = []
    for w in words:
        group = next((g for g in _EQUIVALENTS if w in g), {w})
        for term in sorted(group):
            stem = term[:5] if len(term) > 5 else term
            if stem not in out:
                out.append(stem)
    return out[:24]


@dataclass(frozen=True)
class KnowledgeItem:
    hit: MemoryHit
    reason: str  # "global" | "small_set" | "match"

    def render(self) -> str:
        h = self.hit
        window = ""
        if h.valid_from or h.valid_until:
            window = f", valid {h.valid_from or '...'} to {h.valid_until or '...'}"
        return (
            f"OWNER-CONFIRMED MEMORY [memory:{h.memory_id} v{h.version}, {h.type.lower()}, "
            f"source: {h.source_kind} ({h.source_trust}){window}] - informed by the owner, not externally "
            f"verified: {h.content}"
        )


class KnowledgeContextService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock
        self.memory = MemoryManager(conn, clock)

    def _confirmed(self, employee_id: str, types: tuple[str, ...], limit: int) -> list[MemoryHit]:
        rows = self.conn.execute(
            "SELECT m.id FROM memories m WHERE m.employee_id = ? AND m.status = 'confirmed'"  # noqa: S608
            f" AND m.type IN ({','.join('?' * len(types))}) ORDER BY m.updated_at DESC LIMIT ?",
            (employee_id, *types, limit * 3),
        ).fetchall()
        hits: list[MemoryHit] = []
        for r in rows:
            hit = self.memory.get_current(r[0])
            if hit is not None:  # validity window applied here
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    def context_for(self, employee_id: str, query: str) -> list[KnowledgeItem]:
        items: list[KnowledgeItem] = [
            KnowledgeItem(h, "global")
            for h in self._confirmed(employee_id, ("IDENTITY", "PREFERENCE"), MAX_GLOBAL)
        ]
        seen = {i.hit.memory_id for i in items}
        facts_total = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE employee_id = ? AND status = 'confirmed'"
            " AND type IN ('FACT','EPISODE','PROCEDURE')",
            (employee_id,),
        ).fetchone()[0]
        if facts_total <= SMALL_SET:
            for h in self._confirmed(employee_id, ("FACT", "EPISODE", "PROCEDURE"), SMALL_SET):
                if h.memory_id not in seen:
                    items.append(KnowledgeItem(h, "small_set"))
                    seen.add(h.memory_id)
            return items
        terms = expand_terms(query)
        if not terms:
            return items
        try:
            hits = self.memory.search_terms(employee_id=employee_id, terms=terms, limit=MAX_FACTS)
        except AtlasError:
            return items
        for h in hits:
            if h.memory_id not in seen and h.type in ("FACT", "EPISODE", "PROCEDURE"):
                items.append(KnowledgeItem(h, "match"))
                seen.add(h.memory_id)
        return items
