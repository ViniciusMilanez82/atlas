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
from runtime.verification.criteria import fold, key_terms, stem
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
            text = data.decode("utf-8")
            if art.mime_type == "application/json":
                json.loads(text)
            res.checks["opens"] = True
        except (UnicodeDecodeError, json.JSONDecodeError):
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

    def _coverage(self, task_id: str, body: str, terms: list[str], min_ratio: float) -> str | None:
        if not terms:
            return None
        words = {stem(w) for w in re.findall(r"[a-z0-9]+", fold(body))}
        hit = [t for t in terms if t in words]
        if len(hit) < max(1, math.ceil(min_ratio * len(terms))):
            missing = [t for t in terms if t not in words]
            return f"não atende ao pedido: a entrega não trata de {', '.join(missing)}"
        return None

    def _calculations(self, body: str) -> str | None:
        wrong = []
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
        urls = sorted(set(URL.findall(body)))
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
        for u in urls:  # no research tool has retrieved any page for this task yet
            retrieved = self.conn.execute(
                "SELECT 1 FROM sources WHERE kind = 'web' AND ref = ?", (u,)
            ).fetchone()
            if retrieved:
                valid += 1
            else:
                problems.append(f"fonte citada não foi recuperada nesta tarefa: {u}")
        need = max(minimum, spec.min_sources)
        if valid < need:
            problems.append(
                f"precisa de pelo menos {need} fonte(s) consultada(s) e citada(s); encontrei {valid}"
            )
        return "; ".join(problems) if problems else None

    def _inputs_read(self, task_id: str) -> str | None:
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
        return (
            f"documentos de entrada não foram lidos por completo: {', '.join(missing)}" if missing else None
        )

    # ------------------------------------------------------------------ evidence

    def _evidence(self, task_id: str, artifact_id: str, kind: str, summary: str) -> str:
        eid = new_id()
        self.conn.execute(
            "INSERT INTO evidence(id, task_id, artifact_id, kind, summary, created_at) VALUES (?,?,?,?,?,?)",
            (eid, task_id, artifact_id, kind, summary[:1000], to_utc_str(self.clock.now())),
        )
        return eid

    # ------------------------------------------------------------------ entry point

    def verify_text_artifact(
        self, task_id: str, artifact_id: str, spec: DeliverableSpec
    ) -> VerificationResult:
        res = VerificationResult(artifact_id, passed=False)
        body = self._integrity(task_id, artifact_id, spec, res)
        criteria = self.conn.execute(
            "SELECT id, description, required, check_kind, params_json FROM task_criteria WHERE task_id = ?"
            " ORDER BY rowid",
            (task_id,),
        ).fetchall()
        if body is None:
            return res
        integrity_ok = all(res.checks.values())
        task = self.conn.execute("SELECT objective FROM tasks WHERE id = ?", (task_id,)).fetchone()
        request_terms = key_terms(task[0]) if task else []
        # Business checks (run once; each criterion maps to one of them).
        checks: dict[str, str | None] = {
            "integrity": None if integrity_ok else "; ".join(res.gaps) or "integrity failed",
            "calculations": self._calculations(body),
            "inputs_read": self._inputs_read(task_id) if self._inputs(task_id) else None,
        }
        results: dict[str, CriterionResult] = {}
        for c in criteria:
            kind = c["check_kind"]
            params = json.loads(c["params_json"]) if c["params_json"] else {}
            if kind == "coverage":
                gap = self._coverage(
                    task_id, body, params.get("terms") or request_terms, params.get("min_ratio", 0.5)
                )
            elif kind == "sources":
                gap = self._sources(task_id, body, int(params.get("min", 0)), spec)
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
                        else self._evidence(task_id, artifact_id, ev_kind, summary)
                    )
        return res
