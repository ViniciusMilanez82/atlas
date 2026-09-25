"""Source retrievals with scope and evidence (R5-08, spec 9, 13.3, 16).

A research adapter (N16, browser/fetch through the mediated network) calls ``record_retrieval`` after
it really fetched a page for a task: the captured content becomes an artifact of that task and the
retrieval keeps the canonical and final URL, hash, time, validity and the adapter's receipt. The
verifier accepts a cited URL only through such a retrieval of the SAME task, or through an explicit
``authorize_reuse`` of a capture of the same employee - never because the URL is merely registered,
belongs to another employee, or has expired for a time-sensitive fact.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from runtime.artifacts.manager import ArtifactManager
from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage.db import transaction

ADAPTER = Actor("control_plane", "research-adapter", "internal")


def canonical_url(url: str) -> str:
    """Scheme/host lower-cased, default port and fragment dropped, trailing slash of the path removed."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((parts.scheme == "https" and port == 443) or (parts.scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


class SourceRetrievals:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, artifacts: ArtifactManager) -> None:
        self.conn = conn
        self.clock = clock
        self.artifacts = artifacts

    def record_retrieval(
        self,
        *,
        task_id: str,
        url: str,
        final_url: str,
        content: str,
        adapter: str,
        receipt: dict[str, Any],
        valid_for: timedelta | None = None,
    ) -> str:
        row = self.conn.execute("SELECT employee_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown task")
        art = self.artifacts.create_text(
            actor=ADAPTER,
            employee_id=row[0],
            task_id=task_id,
            name="captura-" + (urlsplit(final_url).hostname or "fonte") + ".txt",
            content=content,
        )
        rid = new_id()
        now = self.clock.now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO source_retrievals(id, employee_id, task_id, url, final_url, artifact_id, content_sha256,"
                " adapter, receipt_json, retrieved_at, valid_until) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    row[0],
                    task_id,
                    canonical_url(url),
                    canonical_url(final_url),
                    art.id,
                    hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    adapter,
                    json.dumps(receipt, sort_keys=True),
                    to_utc_str(now),
                    to_utc_str(now + valid_for) if valid_for else None,
                ),
            )
        return rid

    def authorize_reuse(self, *, task_id: str, retrieval_id: str, actor: Actor) -> None:
        """The owner lets THIS task use an earlier capture of the same employee (no new fetch)."""
        task = self.conn.execute("SELECT employee_id, owner_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        ret = self.conn.execute("SELECT employee_id FROM source_retrievals WHERE id = ?", (retrieval_id,)).fetchone()
        if task is None or ret is None or task[0] != ret[0]:
            raise AtlasError(ErrorCode.INVALID_INPUT, "capture not found for this employee")
        if actor.kind != "owner" or actor.id != task[1]:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner authorizes reusing a capture")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO source_uses(task_id, retrieval_id, authorized_by, created_at) VALUES (?,?,?,?)",
                (task_id, retrieval_id, f"{actor.kind}:{actor.id}", to_utc_str(self.clock.now())),
            )

    def for_task(self, task_id: str, url: str) -> list[sqlite3.Row]:
        """Retrievals of ``url`` usable by this task: its own, or explicitly reused of the same employee."""
        u = canonical_url(url)
        return list(
            self.conn.execute(
                "SELECT r.* FROM source_retrievals r JOIN tasks t ON t.id = ? AND t.employee_id = r.employee_id"
                " WHERE (r.url = ? OR r.final_url = ?) AND (r.task_id = t.id OR EXISTS (SELECT 1 FROM source_uses s"
                " WHERE s.task_id = t.id AND s.retrieval_id = r.id)) ORDER BY r.retrieved_at DESC",
                (task_id, u, u),
            ).fetchall()
        )

    def valid(self, row: sqlite3.Row) -> bool:
        return row["valid_until"] is None or parse_utc(row["valid_until"]) > self.clock.now()
