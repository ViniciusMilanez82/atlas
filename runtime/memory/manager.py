"""Memory Manager (spec 8, AT-013, GA-01, GA-04, threat T-02).

Layers: IDENTITY, PREFERENCE, FACT, EPISODE, PROCEDURE (working memory lives in task checkpoints).
Every memory keeps its source; content from untrusted sources (web pages, documents, e-mails,
tool output) is stored only as ``proposed`` and can never become a confirmed preference,
identity or procedure without the owner. Policies and credentials are not memories: SECRET
sensitivity and credential-shaped content are refused.

Corrections create a new version and supersede the old one without deleting it. Deletion removes
content and derived index entries under Atlas control. The FTS5 index is derived and can be
rebuilt from canonical rows at any time. A semantic (embedding) index is a later, optional layer
and is not required for correctness.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.redaction import Redactor
from storage import journal
from storage.db import require_transaction, transaction

TYPES = ("IDENTITY", "PREFERENCE", "FACT", "EPISODE", "PROCEDURE")
OWNER_ONLY_TYPES = ("IDENTITY", "PREFERENCE", "PROCEDURE")
SOURCE_KINDS = ("owner_message", "document", "web", "tool", "system")
_SECRETISH = Redactor()


@dataclass(frozen=True)
class MemoryHit:
    memory_id: str
    type: str
    status: str
    version: int
    content: str
    source_id: str
    source_kind: str
    source_trust: str
    valid_from: str | None
    valid_until: str | None


STOPWORDS = frozenset(
    "a o as os um uma de da do das dos e em no na nos nas para por com sem que se ao aos the and or of to in for "
    "with on is are be this that".split()
)


def _fts_query(text: str, match_any: bool = False) -> str:
    """Turn free text into a safe FTS5 query of quoted terms.

    ``match_any`` (used for context retrieval) ORs the significant terms and lets bm25 rank; the default
    requires every term (precise lookups).
    """
    terms = re.findall(r"\w+", text, flags=re.UNICODE)
    if match_any:
        terms = [t for t in terms if len(t) >= 4 and t.lower() not in STOPWORDS]
    if not terms:
        raise AtlasError(ErrorCode.INVALID_INPUT, "empty search query")
    return (" OR " if match_any else " AND ").join(f'"{t}"' for t in terms[:32])


class MemoryManager:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # ------------------------------------------------------------------ sources

    def add_source(self, *, actor: Actor, kind: str, ref: str) -> str:
        """Register provenance. Trust is derived from who/what produced it, never from the text."""
        if kind not in SOURCE_KINDS:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"unknown source kind {kind}")
        if kind == "owner_message":
            if actor.kind != "owner":
                raise AtlasError(
                    ErrorCode.UNAUTHORIZED, "owner_message sources come only from the owner channel"
                )
            trust = "owner_authenticated"
        elif kind == "system":
            trust = "verified"
        else:
            trust = "untrusted"
        sid = new_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO sources(id, kind, trust, ref, captured_at) VALUES (?,?,?,?,?)",
                (sid, kind, trust, ref[:512], to_utc_str(self.clock.now())),
            )
        return sid

    def _source(self, source_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown source")
        return row

    # ------------------------------------------------------------------ writes

    @staticmethod
    def _check_content(content: str, sensitivity: str) -> None:
        if sensitivity == "SECRET":
            raise AtlasError(ErrorCode.POLICY_DENIED, "secrets are credentials, not memories; use the Vault")
        if _SECRETISH.redact(content) != content:
            raise AtlasError(
                ErrorCode.POLICY_DENIED, "content looks like a credential; refusing to memorize it"
            )
        if not content.strip():
            raise AtlasError(ErrorCode.INVALID_INPUT, "empty memory")

    def _index_in_txn(self, memory_id: str, content: str) -> None:
        require_transaction(self.conn)
        self.conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        self.conn.execute("INSERT INTO memory_fts(content, memory_id) VALUES (?, ?)", (content, memory_id))

    def propose(
        self,
        *,
        actor: Actor,
        employee_id: str,
        type: str,
        content: str,
        source_id: str,
        sensitivity: str = "INTERNAL",
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> str:
        if type not in TYPES:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"unknown memory type {type}")
        self._check_content(content, sensitivity)
        if valid_from and valid_until and parse_utc(valid_until) <= parse_utc(valid_from):
            raise AtlasError(ErrorCode.INVALID_INPUT, "valid_until must be after valid_from")
        src = self._source(source_id)
        # Only an owner statement on an authenticated channel may be stored as confirmed directly.
        status = (
            "confirmed" if (src["trust"] == "owner_authenticated" and actor.kind == "owner") else "proposed"
        )
        mid = new_id()
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO memories(id, employee_id, type, status, sensitivity, current_version, created_at,"
                " updated_at) VALUES (?,?,?,?,?,1,?,?)",
                (mid, employee_id, type, status, sensitivity, now, now),
            )
            self.conn.execute(
                "INSERT INTO memory_versions(memory_id, version, content, source_id, valid_from, valid_until,"
                " recorded_at) VALUES (?,1,?,?,?,?,?)",
                (mid, content, source_id, valid_from, valid_until, now),
            )
            self._index_in_txn(mid, content)
            journal.append(
                self.conn,
                self.clock,
                employee_id=employee_id,
                type="memory.recorded",
                actor=actor,
                summary=f"{type} memory {mid} recorded as {status} from {src['kind']}",
            )
        return mid

    def _row(self, memory_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown memory")
        return row

    def _owner_of(self, employee_id: str) -> str:
        return str(
            self.conn.execute("SELECT owner_id FROM employees WHERE id = ?", (employee_id,)).fetchone()[0]
        )

    def confirm(self, memory_id: str, *, actor: Actor) -> None:
        """Only the owner turns a proposal into a confirmed memory (spec 8.1, T-02)."""
        row = self._row(memory_id)
        if actor.kind != "owner" or actor.id != self._owner_of(row["employee_id"]):
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner confirms memories")
        if row["status"] not in ("proposed", "disputed"):
            raise AtlasError(ErrorCode.VERSION_CONFLICT, f"memory is {row['status']}")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE memories SET status = 'confirmed', updated_at = ? WHERE id = ?",
                (to_utc_str(self.clock.now()), memory_id),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                type="memory.confirmed",
                actor=actor,
                summary=f"memory {memory_id} confirmed",
            )

    def dispute(self, memory_id: str, *, actor: Actor) -> None:
        row = self._row(memory_id)
        if row["status"] in ("deleted", "superseded"):
            raise AtlasError(ErrorCode.VERSION_CONFLICT, f"memory is {row['status']}")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE memories SET status = 'disputed', updated_at = ? WHERE id = ?",
                (to_utc_str(self.clock.now()), memory_id),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                type="memory.disputed",
                actor=actor,
                summary=f"memory {memory_id} disputed",
            )

    def correct(
        self, memory_id: str, *, actor: Actor, expected_version: int, content: str, source_id: str
    ) -> int:
        """New version supersedes the old one; history stays traceable (spec 8.3)."""
        row = self._row(memory_id)
        if row["status"] == "deleted":
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "memory was deleted")
        if row["current_version"] != expected_version:
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "memory changed; refresh and retry")
        self._check_content(content, row["sensitivity"])
        src = self._source(source_id)
        owner_statement = src["trust"] == "owner_authenticated" and actor.kind == "owner"
        if row["type"] in OWNER_ONLY_TYPES and not owner_statement:
            raise AtlasError(
                ErrorCode.UNAUTHORIZED, "identity, preferences and procedures are corrected only by the owner"
            )
        status = "confirmed" if owner_statement else "proposed"
        new_version = expected_version + 1
        now = to_utc_str(self.clock.now())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO memory_versions(memory_id, version, content, source_id, recorded_at)"
                " VALUES (?,?,?,?,?)",
                (memory_id, new_version, content, source_id, now),
            )
            cur = self.conn.execute(
                "UPDATE memories SET current_version = ?, status = ?, updated_at = ? WHERE id = ? AND current_version = ?",
                (new_version, status, now, memory_id, expected_version),
            )
            if cur.rowcount != 1:
                raise AtlasError(ErrorCode.VERSION_CONFLICT, "memory changed concurrently")
            self._index_in_txn(memory_id, content)
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                type="memory.corrected",
                actor=actor,
                summary=f"memory {memory_id} v{expected_version} -> v{new_version}",
            )
        return new_version

    def delete(self, memory_id: str, *, actor: Actor) -> None:
        """Remove content and derived index entries under Atlas control (spec 16.3).

        External backups are not touched; the UI must say so (see OPERATIONS.md).
        """
        row = self._row(memory_id)
        if actor.kind != "owner" or actor.id != self._owner_of(row["employee_id"]):
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner deletes memories")
        with transaction(self.conn):
            self.conn.execute("UPDATE memory_versions SET content = '' WHERE memory_id = ?", (memory_id,))
            self.conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            self.conn.execute(
                "UPDATE memories SET status = 'deleted', updated_at = ? WHERE id = ?",
                (to_utc_str(self.clock.now()), memory_id),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                type="memory.deleted",
                actor=actor,
                summary=f"memory {memory_id} deleted (content and index removed)",
            )

    # ------------------------------------------------------------------ reads

    def search(
        self,
        *,
        employee_id: str,
        query: str,
        include_proposed: bool = False,
        at: datetime | None = None,
        limit: int = 20,
        match_any: bool = False,
    ) -> list[MemoryHit]:
        """Text search restricted to one employee, current versions and the validity window.

        Results always carry their source so the caller can retrieve the original evidence.
        """
        # Always three placeholders so the SQL text is constant.
        statuses = ("confirmed", "proposed", "disputed") if include_proposed else ("confirmed",) * 3
        when = at or self.clock.now()
        rows = self.conn.execute(
            "SELECT m.id, m.type, m.status, m.current_version, v.content, v.source_id, v.valid_from,"
            " v.valid_until, s.kind AS source_kind, s.trust AS source_trust"
            " FROM memory_fts f JOIN memories m ON m.id = f.memory_id"
            " JOIN memory_versions v ON v.memory_id = m.id AND v.version = m.current_version"
            " JOIN sources s ON s.id = v.source_id"
            " WHERE memory_fts MATCH ? AND m.employee_id = ? AND m.status IN (?, ?, ?)"
            " ORDER BY bm25(memory_fts) LIMIT ?",
            (_fts_query(query, match_any), employee_id, *statuses, limit * 3),
        ).fetchall()
        hits: list[MemoryHit] = []
        for r in rows:
            if r["valid_from"] and parse_utc(r["valid_from"]) > when:
                continue
            if r["valid_until"] and parse_utc(r["valid_until"]) <= when:
                continue
            hits.append(
                MemoryHit(
                    r["id"],
                    r["type"],
                    r["status"],
                    r["current_version"],
                    r["content"],
                    r["source_id"],
                    r["source_kind"],
                    r["source_trust"],
                    r["valid_from"],
                    r["valid_until"],
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def history(self, memory_id: str) -> list[tuple[int, str, str]]:
        """(version, content, source_id) oldest first. Superseded versions remain traceable."""
        return [
            (r["version"], r["content"], r["source_id"])
            for r in self.conn.execute(
                "SELECT version, content, source_id FROM memory_versions WHERE memory_id = ? ORDER BY version",
                (memory_id,),
            )
        ]

    def rebuild_index(self) -> int:
        """Drop and rebuild the derived FTS index from canonical current versions."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM memory_fts")
            rows = self.conn.execute(
                "SELECT m.id, v.content FROM memories m JOIN memory_versions v"
                " ON v.memory_id = m.id AND v.version = m.current_version WHERE m.status <> 'deleted'"
            ).fetchall()
            for r in rows:
                self.conn.execute("INSERT INTO memory_fts(content, memory_id) VALUES (?, ?)", (r[1], r[0]))
        return len(rows)
