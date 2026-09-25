"""Objective deliverable verification, criterion by criterion (spec 13.3; A3-07, A3-08; scenario T23).

A task is COMPLETED only when every required criterion has its OWN evidence produced by deterministic
checks here - never because the model said "done", and never because the file merely opens:

* integrity - exists in the store with a matching hash, belongs to the task, opens for its type, has
  minimum content, no real placeholder (Portuguese "todo" is a word, ``TODO:`` is a marker);
* coverage - the deliverable addresses the terms of the owner's request;
* calculations - every "a op b = c" stated in the text is recomputed with decimals;
* sources - every cited source was really retrieved in THIS task (an attached input that was read; a
  URL only if it was fetched by a research tool); a string that looks like a URL is not a source;
* inputs_read - every analysable input document was read to the end (coverage recorded by pages);
* required_terms - phrases the owner asked for explicitly.

Checks are evidence, not truth: a second model may help with subjective quality but is never proof.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from runtime.artifacts.manager import ArtifactManager
from runtime.verification.conditions import DATE, MONEY, money_value
from runtime.verification.criteria import fold, key_terms, stem
from runtime.verification.substance import Expectations, check_substance, check_totals
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError
from shared.ids import new_id
from storage.db import transaction

# A3-08: explicit markers only. "todo"/"Todo" (Portuguese "all/every") is ordinary text.
PLACEHOLDERS = re.compile(
    r"((?i:lorem ipsum)|\[(?i:inserir|insert|preencher|completar)[^\]]*\]|\{\{[^}]*\}\}|<placeholder>"
    r"|\bTODO\s*[:(\-]|\bTODO\s*$|\bFIXME\b|\bTBD\b|\bXXX+\b)",
    re.MULTILINE,
)
URL = re.compile(r"https?://[^\s)>\]]+")
ARTIFACT_REF = re.compile(r"artifact:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
ARITH = re.compile(_NUM + r"\s*([+\-−x×*/÷])\s*" + _NUM + r"\s*=\s*" + _NUM)


def _dec(pt_number: str) -> Decimal:
    return Decimal(pt_number.replace(".", "").replace(",", "."))


@dataclass(frozen=True)
class DeliverableSpec:
    """Extra integrity constraints (e.g. from a scenario). Business criteria come from the task."""

    min_chars: int = 200
    required_terms: tuple[str, ...] = ()
    min_sources: int = 0
    allowed_source_prefixes: tuple[str, ...] = ()  # e.g. ("artifact:", "https://")


@dataclass
class CriterionResult:
    passed: bool
    gap: str | None = None
    evidence_id: str | None = None


@dataclass
class VerificationResult:
    artifact_id: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    evidence_id: str | None = None  # integrity evidence (kept for callers of the Alpha API)
    criteria: dict[str, CriterionResult] = field(default_factory=dict)  # criterion_id -> result
    instruction_revision: int = 1  # the revision this verification evaluated (R5-04)


class Verifier:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, artifacts: ArtifactManager) -> None:
        self.conn = conn
        self.clock = clock
        self.artifacts = artifacts

    # ------------------------------------------------------------------ individual checks

    def _integrity(
        self, task_id: str, artifact_id: str, spec: DeliverableSpec, res: VerificationResult
    ) -> str | None:
        try:
            art = self.artifacts.get(artifact_id)
            data = self.artifacts.read_bytes(artifact_id)  # re-hashes the stored bytes
            res.checks["exists_and_hash_matches"] = True
        except AtlasError as exc:
            res.checks["exists_and_hash_matches"] = False
            res.gaps.append(f"artifact unavailable: {exc.message}")
            return None
        if art.task_id != task_id:
            res.gaps.append("artifact does not belong to this task")
            res.checks["belongs_to_task"] = False
            return None
        res.checks["belongs_to_task"] = True
        try:
            if art.name.lower().endswith((".pdf", ".docx", ".xlsx", ".pptx")):
                # Binary deliverables open when the format extractor reads them back (N11).
                from runtime.documents.extract import READY, extract

                ex = extract(data, art.name)
                if ex.state != READY:
                    raise ValueError(ex.diagnostic or ex.state)
                text = "\n".join(s.text for s in ex.segments)
            else:
                text = data.decode("utf-8")
                if art.mime_type == "application/json":
                    json.loads(text)
            res.checks["opens"] = True
        except (UnicodeDecodeError, ValueError):
            res.checks["opens"] = False
            res.gaps.append("file does not open as its declared type")
            return None
        body = text.strip()
        res.checks["min_content"] = len(body) >= spec.min_chars
        if not res.checks["min_content"]:
            res.gaps.append(f"content too short ({len(body)} < {spec.min_chars} characters)")
        placeholders = PLACEHOLDERS.findall(body)
        res.checks["no_placeholders"] = not placeholders
        if placeholders:
            res.gaps.append(
                f"placeholders present: {sorted({p if isinstance(p, str) else p[0] for p in placeholders})}"
            )
        lower = body.lower()
        missing = [t for t in spec.required_terms if t.lower() not in lower]
        res.checks["required_terms"] = not missing
        if missing:
            res.gaps.append(f"missing required content: {missing}")
        return body

    def _coverage(
        self, task_id: str, body: str, terms: list[str], min_ratio: float, structure_ok: bool = False
    ) -> str | None:
        """Auxiliary signal (R5-05): the request's terms, OR the verified structure the request asks for
        plus at least one of its terms - so a correct paraphrase passes and an unrelated text does not."""
        if not terms:
            return None
        words = {stem(w) for w in re.findall(r"[a-z0-9]+", fold(body))}
        hit = [t for t in terms if t in words]
        if structure_ok and hit:
            return None
        if len(hit) < max(1, math.ceil(min_ratio * len(terms))):
            missing = [t for t in terms if t not in words]
            return f"não atende ao pedido: a entrega não trata de {', '.join(missing)}"
        return None

    def _calculations(self, body: str) -> str | None:
        wrong = list(check_totals(body)[1])  # labelled totals in prose, tables and cells (R5-05)
        for a, op, b, c in ARITH.findall(body):
            try:
                x, y, z = _dec(a), _dec(b), _dec(c)
                got = {
                    "+": x + y,
                    "-": x - y,
                    "−": x - y,
                    "x": x * y,
                    "×": x * y,
                    "*": x * y,
                    "/": x / y if y else None,
                    "÷": x / y if y else None,
                }[op]
            except (InvalidOperation, KeyError):
                continue
            if got is None or abs(got - z) > Decimal("0.01"):
                wrong.append(f"{a} {op} {b} = {c} (correto: {got})")
        return f"cálculo incorreto: {'; '.join(wrong)}" if wrong else None

    # ------------------------------------------------------------------ conditions (R5-02, R5-05)

    @staticmethod
    def _sentences(body: str) -> list[str]:
        return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n+", body) if s.strip()]

    def _condition(self, body: str, params: dict[str, str]) -> str | None:
        kind, value, span = params.get("kind", ""), params.get("value", ""), params.get("span", "")
        if kind == "DATE":
            want = DATE.match(value)
            dates = {(int(d.group(1)), int(d.group(2))) for d in DATE.finditer(body)}
            if want and (int(want.group(1)), int(want.group(2))) not in dates:
                return f"não trata a data pedida ({value}) - «{span[:100]}»"
            return None
        if kind == "MONEY_CAP":
            cap = money_value(value)
            if cap is None:
                return None
            amounts = [(s, money_value(m.group(2))) for s in self._sentences(body) for m in MONEY.finditer(s)]
            if not amounts:
                return f"não demonstra valores frente ao teto de {value} - «{span[:100]}»"
            over = [
                s for s, v in amounts
                if v is not None and v > cap and re.search(r"total|final|recomend|escolh|selecion", fold(s))
                # an option shown as over the cap and discarded respects the condition
                and not re.search(r"acima do teto|descart|exced|nao atende|fora do|eliminad|rejeitad", fold(s))
            ]
            if over:
                return f"ultrapassa o teto de {value}: «{over[0][:120]}»"
            return None
        if kind == "INCLUDE":
            items = [t for t in key_terms(value) if t not in ("total",)] or key_terms(value)
            words = {stem(w) for w in re.findall(r"[a-z0-9]+", fold(body))}
            missing = [t for t in items if t not in words]
            return f"faltou incluir: {', '.join(missing)} - «{span[:100]}»" if missing else None
        if kind == "SEPARATE":
            terms = key_terms(value) or [stem(w) for w in re.findall(r"[a-z0-9]{4,}", fold(value))]
            hits = [
                s for s in self._sentences(body)
                if terms and all(t in {stem(w) for w in re.findall(r"[a-z0-9]+", fold(s))} for t in terms)
            ]
            if not hits or not any(re.search(r"\d", s) for s in hits):
                return f"não apresenta separadamente: {value} - «{span[:100]}»"
            return None
        if kind == "EXCLUSION":
            terms = key_terms(value)
            if not terms:
                return None
            for s in self._sentences(body):
                words = {stem(w) for w in re.findall(r"[a-z0-9]+", fold(s))}
                if sum(t in words for t in terms) * 2 < len(terms) or len(terms) == 0:
                    continue
                f = fold(s)
                if re.search(r"recomend|escolh|selecion|indicad|melhor op|vencedor", f) and not re.search(
                    r"\b(nao|exclu\w*|descart\w*|sem|fora)\b", f
                ):
                    return f"usa/recomenda o que foi excluído ({value}): «{s[:120]}»"
            return None
        # QUANTITY / PRIORITY: not provable by code here; reported as a limitation, never as verified
        return "não verificado automaticamente (exige revisão)"

    def _inputs(self, task_id: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT artifact_id FROM artifact_links WHERE task_id = ? AND relation = 'input'", (task_id,)
            )
        ]

    def _was_read(self, task_id: str, artifact_id: str) -> bool:
        return bool(
            self.conn.execute(
                "SELECT 1 FROM document_reads WHERE task_id = ? AND artifact_id = ?", (task_id, artifact_id)
            ).fetchone()
            or self.conn.execute(
                "SELECT 1 FROM actions WHERE task_id = ? AND status = 'CONFIRMED' AND tool_id IN"
                " ('artifact.read_text','documents.read') AND instr(input_json, ?) > 0",
                (task_id, artifact_id),
            ).fetchone()
        )

    def _sources(self, task_id: str, body: str, minimum: int, spec: DeliverableSpec) -> str | None:
        inputs = set(self._inputs(task_id))
        cited_arts = sorted(set(ARTIFACT_REF.findall(body)))
        urls = sorted({u.rstrip(".,;:") for u in URL.findall(body)})  # "Fonte: https://x/a." cites x/a
        if spec.allowed_source_prefixes:
            urls = [u for u in urls if u.startswith(spec.allowed_source_prefixes)]
        problems = []
        valid = 0
        for aid in cited_arts:
            if aid not in inputs:
                problems.append(f"fonte citada não é um anexo desta tarefa: artifact:{aid}")
            elif not self._was_read(task_id, aid):
                problems.append(f"fonte citada não foi consultada nesta tarefa: artifact:{aid}")
            else:
                valid += 1
        from runtime.research.sources import SourceRetrievals

        retrievals = SourceRetrievals(self.conn, self.clock, self.artifacts)
        for u in urls:  # R5-08: registered is not retrieved; only a retrieval scoped to THIS task counts
            rows = retrievals.for_task(task_id, u)
            if not rows:
                problems.append(f"fonte citada não foi recuperada nesta tarefa: {u}")
                continue
            fresh = [r for r in rows if retrievals.valid(r)]
            if not fresh:
                problems.append(f"a consulta a {u} expirou para um dado que muda com o tempo; consulte de novo")
                continue
            unsupported = self._unsupported_claim(body, u, fresh[0]["artifact_id"])
            if unsupported:
                problems.append(f"a fonte {u} não sustenta a afirmação: «{unsupported[:120]}»")
                continue
            valid += 1
        need = max(minimum, spec.min_sources)
        if valid < need:
            problems.append(
                f"precisa de pelo menos {need} fonte(s) consultada(s) e citada(s); encontrei {valid}"
            )
        return "; ".join(problems) if problems else None

    def _unsupported_claim(self, body: str, url: str, artifact_id: str) -> str | None:
        """The sentence citing ``url`` must be backed by the captured content: every number it states
        appears there, or (without numbers) at least one of its significant terms does."""
        captured = fold(self.artifacts.read_bytes(artifact_id).decode("utf-8", errors="replace"))
        numbers_in_capture = set(re.findall(r"\d+(?:[.,]\d+)*", captured))
        words = {stem(w) for w in re.findall(r"[a-z0-9]+", captured)}
        parts = self._sentences(body)
        for i, sentence in enumerate(parts):
            if url not in sentence:
                continue
            claim = re.sub(r"(?i)\b(fontes?|refer[eê]ncias?|dispon[ií]vel em|acesso em|consultad[oa] em)\b", " ",
                           sentence.replace(url, " "))
            if not key_terms(claim) and not re.search(r"\d", claim) and i > 0:
                claim = parts[i - 1]  # "Fonte: <url>" on its own backs the previous statement
            numbers = set(re.findall(r"\d+(?:[.,]\d+)*", claim))
            if numbers and not numbers <= numbers_in_capture:
                return claim
            terms = key_terms(claim)
            if not numbers and terms and not any(t in words for t in terms):
                return claim
        return None

    def _inputs_read(self, task_id: str, body: str = "") -> str | None:
        missing = []
        for aid in self._inputs(task_id):
            ext = self.conn.execute(
                "SELECT state, segment_count FROM document_extractions WHERE artifact_id = ?", (aid,)
            ).fetchone()
            name = self.artifacts.get(aid).name
            if ext is None:
                if not self._was_read(task_id, aid):
                    missing.append(f"{name} (não lido)")
                continue
            if ext[0] in ("UNSUPPORTED", "FAILED"):
                missing.append(f"{name} ({'não analisável' if ext[0] == 'UNSUPPORTED' else 'ilegível'})")
                continue
            read = self.conn.execute(
                "SELECT COUNT(*) FROM document_reads WHERE task_id = ? AND artifact_id = ?", (task_id, aid)
            ).fetchone()[0]
            if read < ext[1]:
                missing.append(f"{name} (lido {read} de {ext[1]} trechos)")
            if ext[0] == "PARTIAL":  # R5-06: reading what was extracted is not reading the document
                gone = self.conn.execute(
                    "SELECT missing_json FROM document_extractions WHERE artifact_id = ?", (aid,)
                ).fetchone()[0]
                accepted = self.conn.execute(
                    "SELECT 1 FROM input_scope_acceptances WHERE task_id = ? AND artifact_id = ?", (task_id, aid)
                ).fetchone()
                areas = json.loads(gone)
                if accepted is None:
                    missing.append(
                        f"{name} (extração PARCIAL, não analisado: {', '.join(areas)}; peça material "
                        "legível ou que o proprietário aceite o escopo reduzido)"
                    )
                elif not (
                    any(fold(a) in fold(body) for a in areas)
                    or re.search(r"parcial|nao analisad|ilegive|nao extraid", fold(body))
                ):  # the accepted limitation must be stated, never hidden
                    missing.append(f"{name} (escopo reduzido aceito; a entrega precisa declarar: {', '.join(areas)})")
        return (
            f"documentos de entrada não foram lidos por completo: {', '.join(missing)}" if missing else None
        )

    # ------------------------------------------------------------------ evidence

    def _evidence(self, task_id: str, artifact_id: str, kind: str, summary: str, revision: int) -> str:
        eid = new_id()
        self.conn.execute(
            "INSERT INTO evidence(id, task_id, artifact_id, kind, summary, created_at, instruction_revision)"
            " VALUES (?,?,?,?,?,?,?)",
            (eid, task_id, artifact_id, kind, f"[revision {revision}] {summary}"[:1000], to_utc_str(self.clock.now()),
             revision),
        )
        return eid

    # ------------------------------------------------------------------ entry point

    def verify_text_artifact(
        self, task_id: str, artifact_id: str, spec: DeliverableSpec
    ) -> VerificationResult:
        res = VerificationResult(artifact_id, passed=False)
        rev = self.conn.execute("SELECT instruction_revision FROM tasks WHERE id = ?", (task_id,)).fetchone()
        res.instruction_revision = int(rev[0]) if rev else 1
        body = self._integrity(task_id, artifact_id, spec, res)
        criteria = self.conn.execute(  # superseded criteria are history, not requirements (R5-04)
            "SELECT id, description, required, check_kind, params_json FROM task_criteria WHERE task_id = ?"
            " AND superseded_revision IS NULL ORDER BY rowid",
            (task_id,),
        ).fetchall()
        if body is None:
            return res
        integrity_ok = all(res.checks.values())
        original = self.conn.execute(  # the owner's full request, not a summary (R5-02)
            "SELECT instruction FROM task_instruction_versions WHERE task_id = ? ORDER BY revision LIMIT 1",
            (task_id,),
        ).fetchone()
        request_terms = key_terms(original[0]) if original else []
        # Business checks (run once; each criterion maps to one of them).
        checks: dict[str, str | None] = {
            "integrity": None if integrity_ok else "; ".join(res.gaps) or "integrity failed",
            "calculations": self._calculations(body),
            "inputs_read": self._inputs_read(task_id, body) if self._inputs(task_id) else None,
        }
        results: dict[str, CriterionResult] = {}
        substance = None
        for c in criteria:
            if c["check_kind"] == "substance":
                params = json.loads(c["params_json"]) if c["params_json"] else {}
                substance = check_substance(body, Expectations(**params))
        for c in criteria:
            kind = c["check_kind"]
            params = json.loads(c["params_json"]) if c["params_json"] else {}
            if kind == "coverage":
                gap = self._coverage(
                    task_id,
                    body,
                    params.get("terms") or request_terms,
                    params.get("min_ratio", 0.5),
                    structure_ok=bool(substance and substance.structure_ok and not substance.gaps),
                )
            elif kind == "substance":
                gap = "; ".join(substance.gaps) if substance and substance.gaps else None
            elif kind == "sources":
                gap = self._sources(task_id, body, int(params.get("min", 0)), spec)
            elif kind == "condition":
                gap = self._condition(body, params)
            elif kind == "required_terms":
                missing = [t for t in params.get("terms", []) if fold(t) not in fold(body)]
                gap = f"faltou o que foi pedido: {missing}" if missing else None
            elif kind in checks:
                gap = checks[kind]
            else:  # legacy generic criterion: satisfied only when EVERY check passes (conservative)
                parts = [
                    checks["integrity"],
                    checks["calculations"],
                    checks["inputs_read"],
                    self._coverage(task_id, body, request_terms, 0.5),
                    self._sources(task_id, body, 0, spec),
                ]
                gap = "; ".join(p for p in parts if p) or None
            results[c["id"]] = CriterionResult(gap is None, gap)
            if gap:
                res.gaps.append(f"[{c['description'][:60]}] {gap}")
        res.criteria = results
        required_ok = all(
            r.passed for cid, r in results.items() if any(c["id"] == cid and c["required"] for c in criteria)
        )
        res.passed = integrity_ok and required_ok and (bool(criteria) or not spec.min_sources)
        if not criteria and spec.min_sources:  # no task criteria at all: the spec still demands sources
            gap = self._sources(task_id, body, spec.min_sources, spec)
            res.passed = integrity_ok and gap is None
            if gap:
                res.gaps.append(gap)
        if res.passed:
            with transaction(self.conn):
                art = self.artifacts.get(artifact_id)
                res.evidence_id = self._evidence(
                    task_id,
                    artifact_id,
                    "file_opens",
                    f"'{art.name}' v{art.version} sha256 {art.sha256[:12]}: opens, {len(body)} chars, no placeholders",
                    res.instruction_revision,
                )
                for c in criteria:
                    kind = c["check_kind"] or "all"
                    ev_kind = {"sources": "source_check", "integrity": "file_opens"}.get(
                        kind, "deterministic_check"
                    )
                    summary = f"{kind}: {c['description'][:200]} - verified on '{art.name}' v{art.version}"
                    results[c["id"]].evidence_id = (
                        res.evidence_id
                        if kind == "integrity"
                        else self._evidence(task_id, artifact_id, ev_kind, summary, res.instruction_revision)
                    )
        return res
