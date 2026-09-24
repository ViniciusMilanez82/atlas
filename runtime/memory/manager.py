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

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
_UNSET: Any = object()
REDACTED = "[conteúdo apagado a pedido do proprietário]"
FORGET_SCOPES = ("stop_using", "erase")


def content_hash(text: str) -> str:
    """Hash of the normalized content: what a tombstone keeps instead of the content itself."""
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()


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
    sensitivity: str = "INTERNAL"


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

    def add_source(self, *, actor: Actor, kind: str, ref: str, employee_id: str | None = None) -> str:
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
                "INSERT INTO sources(id, kind, trust, ref, captured_at, employee_id) VALUES (?,?,?,?,?,?)",
                (sid, kind, trust, ref[:512], to_utc_str(self.clock.now()), employee_id),
            )
        return sid

    def _source(self, source_id: str, employee_id: str | None = None) -> sqlite3.Row:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None or (employee_id is not None and row["employee_id"] not in (None, employee_id)):
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown source")  # same answer: reveals nothing (A3-26)
        return row

    def _is_forgotten(self, employee_id: str, content: str) -> bool:
        h = content_hash(content)
        for row in self.conn.execute(
            "SELECT content_hashes_json FROM forget_tombstones WHERE employee_id = ?", (employee_id,)
        ):
            if h in json.loads(row[0]):
                return True
        return False

    def require_owned(self, memory_id: str, employee_id: str) -> sqlite3.Row:
        """The memory exists AND belongs to this employee; otherwise the same 'not found' (A3-26)."""
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row is None or row["employee_id"] != employee_id:
            raise AtlasError(ErrorCode.INVALID_INPUT, "memory not found for this employee")
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
        require_confirmation: bool = False,
    ) -> str:
        """``require_confirmation`` keeps even an owner statement as a proposal until the owner confirms the
        exact text that will be stored (used when memory is requested from the conversation)."""
        if type not in TYPES:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"unknown memory type {type}")
        self._check_content(content, sensitivity)
        if valid_from and valid_until and parse_utc(valid_until) <= parse_utc(valid_from):
            raise AtlasError(ErrorCode.INVALID_INPUT, "valid_until must be after valid_from")
        src = self._source(source_id, employee_id)
        if src["kind"] != "owner_message" and self._is_forgotten(employee_id, content):
            # A3-17: a summary, document or tool output cannot bring back what the owner forgot.
            raise AtlasError(ErrorCode.POLICY_DENIED, "this content was forgotten by the owner; not stored again")
        # Only an owner statement on an authenticated channel may be stored as confirmed directly.
        owner_statement = src["trust"] == "owner_authenticated" and actor.kind == "owner"
        status = "confirmed" if owner_statement and not require_confirmation else "proposed"
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
        self,
        memory_id: str,
        *,
        actor: Actor,
        expected_version: int,
        content: str,
        source_id: str,
        employee_id: str | None = None,
        valid_from: Any = _UNSET,
        valid_until: Any = _UNSET,
        change_validity: bool = False,
    ) -> int:
        """New version supersedes the old one; history stays traceable (spec 8.3).

        The validity window of the previous version is KEPT unless ``change_validity`` is set with the
        new window (A3-16): correcting the text never silently changes when a fact is valid."""
        row = self._row(memory_id) if employee_id is None else self.require_owned(memory_id, employee_id)
        if actor.kind == "owner" and actor.id != self._owner_of(row["employee_id"]):
            raise AtlasError(ErrorCode.INVALID_INPUT, "memory not found for this employee")
        if row["status"] == "deleted":
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "memory was deleted")
        if row["current_version"] != expected_version:
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "memory changed; refresh and retry")
        self._check_content(content, row["sensitivity"])
        src = self._source(source_id, row["employee_id"])
        owner_statement = src["trust"] == "owner_authenticated" and actor.kind == "owner"
        if row["type"] in OWNER_ONLY_TYPES and not owner_statement:
            raise AtlasError(
                ErrorCode.UNAUTHORIZED, "identity, preferences and procedures are corrected only by the owner"
            )
        status = "confirmed" if owner_statement else "proposed"
        new_version = expected_version + 1
        now = to_utc_str(self.clock.now())
        prev = self.conn.execute(
            "SELECT valid_from, valid_until FROM memory_versions WHERE memory_id = ? AND version = ?",
            (memory_id, expected_version),
        ).fetchone()
        if change_validity:
            new_from = None if valid_from is _UNSET else valid_from
            new_until = None if valid_until is _UNSET else valid_until
        else:
            new_from, new_until = (prev[0], prev[1]) if prev else (None, None)
        if new_from and new_until and parse_utc(new_until) <= parse_utc(new_from):
            raise AtlasError(ErrorCode.INVALID_INPUT, "valid_until must be after valid_from")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO memory_versions(memory_id, version, content, source_id, valid_from, valid_until,"
                " recorded_at) VALUES (?,?,?,?,?,?,?)",
                (memory_id, new_version, content, source_id, new_from, new_until, now),
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

    def _forget_targets(self, memory_id: str) -> tuple[sqlite3.Row, list[str], list[str], list[str]]:
        """What forgetting this memory reaches under Atlas control (A3-17, spec 8.4): its versions, the
        owner message it came from, the confirmation echo, and messages/observations of the same employee
        that contain the exact content. Copies outside Atlas (provider logs, exports) are NOT reachable."""
        row = self._row(memory_id)
        contents = [
            r[0] for r in self.conn.execute(
                "SELECT content FROM memory_versions WHERE memory_id = ? AND content <> ''", (memory_id,)
            )
        ]
        refs = [
            r[0][len("message:"):]
            for r in self.conn.execute(
                "SELECT s.ref FROM memory_versions v JOIN sources s ON s.id = v.source_id WHERE v.memory_id = ?",
                (memory_id,),
            )
            if r[0].startswith("message:")
        ]
        msgs = {r[0] for r in self.conn.execute("SELECT id FROM messages WHERE memory_id = ?", (memory_id,))}
        for ref in refs:  # the owner message the memory came from, only inside this employee's scope
            hit = self.conn.execute(
                "SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id"
                " WHERE m.id = ? AND c.employee_id = ?",
                (ref, row["employee_id"]),
            ).fetchone()
            if hit:
                msgs.add(str(hit[0]))
        obs: set[str] = set()
        for text in contents:
            for r in self.conn.execute(
                "SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id"
                " WHERE c.employee_id = ? AND instr(m.content, ?) > 0",
                (row["employee_id"], text),
            ):
                msgs.add(r[0])
            for r in self.conn.execute(
                "SELECT o.step_id FROM step_observations o JOIN tasks t ON t.id = o.task_id"
                " WHERE t.employee_id = ? AND instr(o.content, ?) > 0",
                (row["employee_id"], text),
            ):
                obs.add(r[0])
        return row, contents, sorted(msgs), sorted(obs)

    def forget_preview(self, memory_id: str) -> dict[str, Any]:
        _, contents, msgs, obs = self._forget_targets(memory_id)
        return {
            "memory_versions": len(contents),
            "messages": len(msgs),
            "observations": len(obs),
            "outside_atlas": "cópias fora do Atlas (provedor de IA, arquivos exportados, backups antigos) "
            "não são apagadas por aqui; backups restaurados reaplicam esta exclusão",
        }

    def _apply_forget_in_txn(
        self, scope: str, memory_id: str | None, msgs: list[str], obs: list[str]
    ) -> None:
        require_transaction(self.conn)
        if memory_id is not None:
            self.conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            self.conn.execute(
                "UPDATE memories SET status = 'deleted', updated_at = ? WHERE id = ?",
                (to_utc_str(self.clock.now()), memory_id),
            )
            if scope == "erase":
                self.conn.execute("UPDATE memory_versions SET content = '' WHERE memory_id = ?", (memory_id,))
        for mid in msgs:
            if scope == "erase":
                self.conn.execute(
                    "UPDATE messages SET content = ?, classification = 'INTERNAL', context_excluded = 1 WHERE id = ?",
                    (REDACTED, mid),
                )
            else:
                self.conn.execute("UPDATE messages SET context_excluded = 1 WHERE id = ?", (mid,))
        if scope == "erase":
            for sid in obs:
                self.conn.execute("UPDATE step_observations SET content = ? WHERE step_id = ?", (REDACTED, sid))

    def delete(self, memory_id: str, *, actor: Actor, scope: str = "erase") -> dict[str, Any]:
        """Forget a memory (spec 8.4, A3-17).

        ``stop_using``: never retrieved nor sent to a model again; history stays visible to the owner.
        ``erase``: content removed from the memory, its index, the source message, the confirmation echo
        and every message/observation of this employee containing it. A tombstone (ids + content hashes,
        never the content) blocks reintroduction by derived sources and is re-applied after a restore.
        """
        if scope not in FORGET_SCOPES:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"unknown forget scope {scope}")
        row, contents, msgs, obs = self._forget_targets(memory_id)
        if actor.kind != "owner" or actor.id != self._owner_of(row["employee_id"]):
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner deletes memories")
        with transaction(self.conn):
            self._apply_forget_in_txn(scope, memory_id, msgs, obs)
            self.conn.execute(
                "INSERT INTO forget_tombstones(id, employee_id, memory_id, scope, content_hashes_json,"
                " message_ids_json, observation_ids_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    row["employee_id"],
                    memory_id,
                    scope,
                    json.dumps(sorted({content_hash(c) for c in contents})),
                    json.dumps(msgs),
                    json.dumps(obs if scope == "erase" else []),
                    to_utc_str(self.clock.now()),
                ),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=row["employee_id"],
                type="memory.deleted",
                actor=actor,
                summary=f"memory {memory_id} forgotten ({scope}): {len(msgs)} message(s), "
                f"{len(obs)} observation(s) under Atlas control",
            )
        return {"scope": scope, "messages": len(msgs), "observations": len(obs)}

    def reapply_tombstones(self, tombstones: list[dict[str, Any]]) -> int:
        """After a backup restore: bring back every forget decision taken after the backup (A3-17)."""
        applied = 0
        with transaction(self.conn):
            for t in tombstones:
                known = self.conn.execute("SELECT 1 FROM forget_tombstones WHERE id = ?", (t["id"],)).fetchone()
                memory_exists = t["memory_id"] and self.conn.execute(
                    "SELECT 1 FROM memories WHERE id = ?", (t["memory_id"],)
                ).fetchone()
                msgs = [
                    m for m in json.loads(t["message_ids_json"])
                    if self.conn.execute("SELECT 1 FROM messages WHERE id = ?", (m,)).fetchone()
                ]
                obs = [
                    o for o in json.loads(t["observation_ids_json"])
                    if self.conn.execute("SELECT 1 FROM step_observations WHERE step_id = ?", (o,)).fetchone()
                ]
                self._apply_forget_in_txn(t["scope"], t["memory_id"] if memory_exists else None, msgs, obs)
                if not known:
                    self.conn.execute(
                        "INSERT INTO forget_tombstones(id, employee_id, memory_id, scope, content_hashes_json,"
                        " message_ids_json, observation_ids_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            t["id"],
                            t["employee_id"],
                            t["memory_id"] if memory_exists else None,
                            t["scope"],
                            t["content_hashes_json"],
                            t["message_ids_json"],
                            t["observation_ids_json"],
                            t["created_at"],
                        ),
                    )
                applied += 1
        return applied

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
            " v.valid_until, s.kind AS source_kind, s.trust AS source_trust, m.sensitivity"
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
                    r["sensitivity"],
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
