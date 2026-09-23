"""Objective deliverable verification (spec 15.2, 15.3; AT-016/M11).

A task is COMPLETED only when its required criteria have evidence produced by deterministic checks
here - never because the model said "done". Checks for a text/JSON deliverable:
exists in the store with a matching hash, opens/parses for its type, has minimum content, contains
no placeholders, mentions required terms, and cites required sources. Each passing check becomes an
``evidence`` row; failures are returned as explicit gaps for repair or a declared partial delivery.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from runtime.artifacts.manager import ArtifactManager
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError
from shared.ids import new_id
from storage.db import transaction

PLACEHOLDERS = re.compile(
    r"(?i)(lorem ipsum|\bTODO\b|\bTBD\b|\bFIXME\b|\[inserir|\[insert|\{\{.*?\}\}|<placeholder>|xxx+)"
)
URL = re.compile(r"https?://[^\s)>\]]+")


@dataclass(frozen=True)
class DeliverableSpec:
    """What 'done' means for one artifact, derived from the task's criteria (not from the model)."""

    min_chars: int = 200
    required_terms: tuple[str, ...] = ()
    min_sources: int = 0
    allowed_source_prefixes: tuple[str, ...] = ()  # e.g. ("artifact:", "https://")


@dataclass
class VerificationResult:
    artifact_id: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    evidence_id: str | None = None


def _sources(text: str, spec: DeliverableSpec) -> list[str]:
    found = URL.findall(text) + re.findall(r"artifact:[0-9a-f-]{36}", text)
    if spec.allowed_source_prefixes:
        found = [s for s in found if s.startswith(spec.allowed_source_prefixes)]
    return sorted(set(found))


class Verifier:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, artifacts: ArtifactManager) -> None:
        self.conn = conn
        self.clock = clock
        self.artifacts = artifacts

    def verify_text_artifact(
        self, task_id: str, artifact_id: str, spec: DeliverableSpec
    ) -> VerificationResult:
        res = VerificationResult(artifact_id, passed=False)
        try:
            art = self.artifacts.get(artifact_id)
            data = self.artifacts.read_bytes(artifact_id)  # re-hashes the stored bytes
            res.checks["exists_and_hash_matches"] = True
        except AtlasError as exc:
            res.checks["exists_and_hash_matches"] = False
            res.gaps.append(f"artifact unavailable: {exc.message}")
            return res
        if art.task_id != task_id:
            res.gaps.append("artifact does not belong to this task")
            res.checks["belongs_to_task"] = False
            return res
        res.checks["belongs_to_task"] = True
        try:
            text = data.decode("utf-8")
            if art.mime_type == "application/json":
                json.loads(text)
            res.checks["opens"] = True
        except (UnicodeDecodeError, json.JSONDecodeError):
            res.checks["opens"] = False
            res.gaps.append("file does not open as its declared type")
            return res
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
        sources = _sources(body, spec)
        res.checks["sources"] = len(sources) >= spec.min_sources
        if not res.checks["sources"]:
            res.gaps.append(f"needs at least {spec.min_sources} cited source(s), found {len(sources)}")
        res.passed = all(res.checks.values())
        if res.passed:
            res.evidence_id = new_id()
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO evidence(id, task_id, artifact_id, kind, summary, created_at) VALUES (?,?,?,?,?,?)",
                    (
                        res.evidence_id,
                        task_id,
                        artifact_id,
                        "file_opens",
                        f"'{art.name}' v{art.version} sha256 {art.sha256[:12]}: opens, {len(body)} chars, "
                        f"{len(sources)} source(s), no placeholders",
                        to_utc_str(self.clock.now()),
                    ),
                )
        return res
