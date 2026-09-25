"""Document segments, paged reading and coverage (A3-09, A3-10; spec 10.3-10.4; scenarios T12, T13).

Extraction runs once per artifact version in a child process with a deadline; segments are stored with
their locator. ``read`` returns complete segments page by page (``next_cursor``/``has_more``, total size)
and records which segments THIS task has read, so "read the whole document" is a verifiable coverage and
not a claim. Nothing is cut in the middle: a page stops at a segment boundary, and each segment fits the
contract. The full content always stays reachable by cursor.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from typing import Any

from runtime.artifacts.manager import ArtifactManager
from runtime.documents.extract import EXTRACTOR_VERSION, FAILED, Extraction, extract_job
from security.broker.executor import run_in_process
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from storage.db import transaction

EXTRACTION_TIMEOUT_S = 120.0
MAX_PAGE_CHARS = 12_000
STATE_TEXT = {
    "READY_FOR_ANALYSIS": "pronto para análise",
    "PARTIAL": "analisável em parte",
    "UNSUPPORTED": "armazenado, mas ainda não analisável",
    "FAILED": "não foi possível ler",
}


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


class DocumentStore:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, artifacts: ArtifactManager) -> None:
        self.conn = conn
        self.clock = clock
        self.artifacts = artifacts

    # ------------------------------------------------------------------ extraction

    def status(self, artifact_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM document_extractions WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": artifact_id,
            "state": row["state"],
            "state_text": STATE_TEXT[row["state"]],
            "extractor": row["extractor"],
            "segments": row["segment_count"],
            "total_chars": row["total_chars"],
            "warnings": json.loads(row["warnings_json"]),
            "diagnostic": row["diagnostic"],
        }

    def ensure_extracted(self, artifact_id: str) -> dict[str, Any]:
        known = self.status(artifact_id)
        if known is not None:
            return known
        art = self.artifacts.get(artifact_id)
        data = self.artifacts.read_bytes(artifact_id)
        rep = run_in_process(extract_job, {"data": data, "name": art.name}, timeout_s=EXTRACTION_TIMEOUT_S)
        if rep.finished and rep.error is None and isinstance(rep.value, Extraction):
            ex = rep.value
        elif rep.timed_out:
            ex = Extraction(FAILED, "none", diagnostic="a extração passou do prazo e foi interrompida")
        else:
            ex = Extraction(FAILED, "none", diagnostic=f"falha na extração ({type(rep.error).__name__})")
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            if self.conn.execute(
                "SELECT 1 FROM document_extractions WHERE artifact_id = ?", (artifact_id,)
            ).fetchone():
                pass  # another connection finished first; its result stands
            else:
                self.conn.execute(
                    "INSERT INTO document_extractions(artifact_id, state, extractor, extractor_version,"
                    " segment_count, total_chars, warnings_json, diagnostic, created_at, units_total, missing_json)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        ex.state,
                        ex.extractor,
                        EXTRACTOR_VERSION,
                        len(ex.segments),
                        sum(len(s.text) for s in ex.segments),
                        json.dumps(ex.warnings, ensure_ascii=False),
                        ex.diagnostic,
                        now,
                        ex.units_total,
                        json.dumps(ex.missing, ensure_ascii=False),
                    ),
                )
                for seq, seg in enumerate(ex.segments):
                    self.conn.execute(
                        "INSERT INTO document_segments(artifact_id, seq, locator, kind, text) VALUES (?,?,?,?,?)",
                        (artifact_id, seq, seg.locator, seg.kind, seg.text),
                    )
                    self.conn.execute(
                        "INSERT INTO document_fts(text, artifact_id, seq) VALUES (?,?,?)",
                        (seg.text, artifact_id, seq),
                    )
        status = self.status(artifact_id)
        assert status is not None
        return status

    # ------------------------------------------------------------------ reading

    def read(
        self, artifact_id: str, *, task_id: str | None, cursor: int = 0, max_chars: int = MAX_PAGE_CHARS
    ) -> dict[str, Any]:
        """One page of COMPLETE segments starting at ``cursor``. Records coverage for ``task_id``."""
        status = self.ensure_extracted(artifact_id)
        art = self.artifacts.get(artifact_id)
        base = {
            "artifact_id": artifact_id,
            "name": art.name,
            "artifact_version": art.version,
            "sha256": art.sha256,
            "classification": art.classification,
            "analysis_state": status["state"],
            "analysis_state_text": status["state_text"],
            "warnings": status["warnings"],
            "total_segments": status["segments"],
            "total_chars": status["total_chars"],
            "trust": "untrusted",
        }
        if status["state"] in ("UNSUPPORTED", "FAILED"):
            return {
                **base,
                "segments": [],
                "next_cursor": None,
                "has_more": False,
                "diagnostic": status["diagnostic"],
                "coverage": self.coverage(task_id, artifact_id),
            }
        if cursor < 0 or cursor > status["segments"]:
            raise AtlasError(ErrorCode.INVALID_INPUT, "cursor outside the document")
        max_chars = max(1_000, min(max_chars, MAX_PAGE_CHARS))
        rows = self.conn.execute(
            "SELECT seq, locator, kind, text FROM document_segments WHERE artifact_id = ? AND seq >= ?"
            " ORDER BY seq",
            (artifact_id, cursor),
        ).fetchall()
        page: list[dict[str, Any]] = []
        used = 0
        for r in rows:
            if page and used + len(r["text"]) > max_chars:
                break
            page.append({"segment": r["seq"], "locator": r["locator"], "kind": r["kind"], "text": r["text"]})
            used += len(r["text"])
        nxt = (page[-1]["segment"] + 1) if page else cursor
        if task_id is not None and page:
            with transaction(self.conn):
                for s in page:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO document_reads(task_id, artifact_id, seq, read_at) VALUES (?,?,?,?)",
                        (task_id, artifact_id, s["segment"], to_utc_str(self.clock.now())),
                    )
        has_more = nxt < status["segments"]
        return {
            **base,
            "segments": page,
            "next_cursor": nxt if has_more else None,
            "has_more": has_more,
            "coverage": self.coverage(task_id, artifact_id),
        }

    def search(
        self, artifact_ids: list[str], query: str, *, task_id: str | None, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Focused lookup by words; a hit is NOT a full reading (coverage records only what was returned)."""
        terms = [t for t in re.findall(r"[a-z0-9]+", _fold(query)) if len(t) >= 3][:12]
        if not terms or not artifact_ids:
            return []
        for aid in artifact_ids:
            self.ensure_extracted(aid)
        rows = self.conn.execute(
            f"SELECT f.artifact_id, f.seq, bm25(document_fts) AS rank FROM document_fts f WHERE document_fts MATCH ?"  # noqa: S608
            f" AND f.artifact_id IN ({','.join('?' * len(artifact_ids))}) ORDER BY rank LIMIT ?",
            (" OR ".join(f"{t}*" for t in terms), *artifact_ids, limit),
        ).fetchall()
        hits = []
        for r in rows:
            seg = self.conn.execute(
                "SELECT locator, text FROM document_segments WHERE artifact_id = ? AND seq = ?", (r[0], r[1])
            ).fetchone()
            hits.append({"artifact_id": r[0], "segment": r[1], "locator": seg[0], "text": seg[1]})
        if task_id is not None and hits:
            with transaction(self.conn):
                for h in hits:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO document_reads(task_id, artifact_id, seq, read_at) VALUES (?,?,?,?)",
                        (task_id, h["artifact_id"], h["segment"], to_utc_str(self.clock.now())),
                    )
        return hits

    def coverage(self, task_id: str | None, artifact_id: str) -> dict[str, Any]:
        """Extraction coverage and reading coverage kept apart (R5-06): reading every extracted segment
        of a PARTIAL document is ``segments_complete``, never ``complete``."""
        total = self.conn.execute(
            "SELECT segment_count, state, missing_json, units_total FROM document_extractions WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        read = 0
        if task_id is not None:
            read = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM document_reads WHERE task_id = ? AND artifact_id = ?",
                    (task_id, artifact_id),
                ).fetchone()[0]
            )
        n = int(total[0]) if total else 0
        segments_complete = n > 0 and read >= n
        partial = bool(total) and total[1] == "PARTIAL"
        return {
            "read_segments": read,
            "total_segments": n,
            "segments_complete": segments_complete,
            "extraction_state": total[1] if total else None,
            "missing": json.loads(total[2]) if total else [],
            "units_total": total[3] if total else None,
            "complete": segments_complete and not partial,
        }
