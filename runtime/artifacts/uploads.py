"""Chunked uploads shared by every connection (A3-24, A3-22; spec 14.1; scenarios T14, T15).

State lives in ``upload_sessions`` and every chunk is appended inside a ``BEGIN IMMEDIATE`` transaction,
so two connections (or two processes) sending the same chunk serialize on the database: the second one
sees the first one's bytes and is answered ``duplicate`` instead of appending them again. Staging has a
per-employee aggregate quota and a TTL; ``UploadSweeper`` removes expired staging without touching
uploads still in progress. The import is recorded on the session in the same transaction that creates
the artifact, which makes ``artifacts.import`` a recoverable receipt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from runtime.artifacts.manager import MAX_IMPORT_BYTES
from shared.clock import Clock, parse_utc, to_utc_str
from shared.errors import AtlasError, ErrorCode
from storage.db import transaction

UPLOAD_TTL = timedelta(hours=1)
MAX_STAGING_BYTES_PER_EMPLOYEE = 200 * 1024 * 1024


@dataclass(frozen=True)
class ChunkResult:
    received_bytes: int
    duplicate: bool


def staging_path(root: Path, employee_id: str, upload_ref: str) -> Path:
    folder = root / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{employee_id}-{upload_ref}.part"


class UploadStore:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, root: Path) -> None:
        self.conn = conn
        self.clock = clock
        self.root = root

    def append(self, employee_id: str, upload_ref: str, offset: int, chunk: bytes) -> ChunkResult:
        now = self.clock.now()
        path = staging_path(self.root, employee_id, upload_ref)
        with transaction(self.conn):  # serializes every connection/process on this upload
            row = self.conn.execute(
                "SELECT * FROM upload_sessions WHERE employee_id = ? AND upload_ref = ?",
                (employee_id, upload_ref),
            ).fetchone()
            if row is None:
                staged = self.conn.execute(
                    "SELECT COALESCE(SUM(received_bytes), 0) FROM upload_sessions WHERE employee_id = ?"
                    " AND state = 'RECEIVING'",
                    (employee_id,),
                ).fetchone()[0]
                if int(staged) + len(chunk) > MAX_STAGING_BYTES_PER_EMPLOYEE:
                    raise AtlasError(
                        ErrorCode.INVALID_INPUT,
                        "staging quota exceeded; finish or cancel other uploads first",
                    )
                self.conn.execute(
                    "INSERT INTO upload_sessions(employee_id, upload_ref, state, received_bytes, created_at,"
                    " updated_at, expires_at) VALUES (?,?,'RECEIVING',0,?,?,?)",
                    (employee_id, upload_ref, to_utc_str(now), to_utc_str(now), to_utc_str(now + UPLOAD_TTL)),
                )
                path.unlink(missing_ok=True)  # never trust a leftover file without a session
                size = 0
            else:
                if row["state"] != "RECEIVING":
                    raise AtlasError(ErrorCode.VERSION_CONFLICT, f"upload is {row['state']}; start a new one")
                size = int(row["received_bytes"])
            if offset < size:  # resend after a lost reply: accepted only when identical
                with path.open("rb") as fh:
                    fh.seek(offset)
                    same = fh.read(len(chunk)) == chunk
                if same and offset + len(chunk) <= size:
                    return ChunkResult(size, True)
                raise AtlasError(ErrorCode.VERSION_CONFLICT, f"upload already has {size} bytes")
            if offset > size:
                raise AtlasError(ErrorCode.VERSION_CONFLICT, f"upload has {size} bytes; resend from there")
            if size + len(chunk) > MAX_IMPORT_BYTES:
                raise AtlasError(ErrorCode.INVALID_INPUT, "file exceeds the import size limit")
            staged = self.conn.execute(
                "SELECT COALESCE(SUM(received_bytes), 0) FROM upload_sessions WHERE employee_id = ?"
                " AND state = 'RECEIVING'",
                (employee_id,),
            ).fetchone()[0]
            if int(staged) + len(chunk) > MAX_STAGING_BYTES_PER_EMPLOYEE:
                raise AtlasError(
                    ErrorCode.INVALID_INPUT, "staging quota exceeded; finish or cancel other uploads first"
                )
            with path.open("r+b" if path.exists() else "wb") as fh:
                fh.seek(size)
                fh.truncate()  # a torn write from a crashed attempt never survives
                fh.write(chunk)
                fh.flush()
            self.conn.execute(
                "UPDATE upload_sessions SET received_bytes = ?, updated_at = ?, expires_at = ?"
                " WHERE employee_id = ? AND upload_ref = ?",
                (size + len(chunk), to_utc_str(now), to_utc_str(now + UPLOAD_TTL), employee_id, upload_ref),
            )
            return ChunkResult(size + len(chunk), False)

    def session(self, employee_id: str, upload_ref: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM upload_sessions WHERE employee_id = ? AND upload_ref = ?",
            (employee_id, upload_ref),
        ).fetchone()
        return row

    def mark_imported_in_txn(self, employee_id: str, upload_ref: str, artifact_id: str) -> None:
        cur = self.conn.execute(
            "UPDATE upload_sessions SET state = 'IMPORTED', artifact_id = ?, updated_at = ?"
            " WHERE employee_id = ? AND upload_ref = ? AND state = 'RECEIVING'",
            (artifact_id, to_utc_str(self.clock.now()), employee_id, upload_ref),
        )
        if cur.rowcount != 1:
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "upload was finalized concurrently")

    def fail(self, employee_id: str, upload_ref: str, why: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE upload_sessions SET state = 'FAILED', failure = ?, updated_at = ?"
                " WHERE employee_id = ? AND upload_ref = ? AND state = 'RECEIVING'",
                (why[:300], to_utc_str(self.clock.now()), employee_id, upload_ref),
            )
        staging_path(self.root, employee_id, upload_ref).unlink(missing_ok=True)


class UploadSweeper:
    """Removes expired staging (recoverably: the session says EXPIRED, the owner just resends)."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock, root: Path) -> None:
        self.conn = conn
        self.clock = clock
        self.root = root

    def sweep(self) -> list[str]:
        now = self.clock.now()
        expired: list[str] = []
        rows = self.conn.execute(
            "SELECT employee_id, upload_ref, expires_at FROM upload_sessions WHERE state = 'RECEIVING'"
        ).fetchall()
        for r in rows:
            if parse_utc(r["expires_at"]) > now:
                continue
            with transaction(self.conn):
                cur = self.conn.execute(
                    "UPDATE upload_sessions SET state = 'EXPIRED', updated_at = ? WHERE employee_id = ?"
                    " AND upload_ref = ? AND state = 'RECEIVING' AND expires_at <= ?",
                    (to_utc_str(now), r["employee_id"], r["upload_ref"], to_utc_str(now)),
                )
                if cur.rowcount == 1:
                    staging_path(self.root, r["employee_id"], r["upload_ref"]).unlink(missing_ok=True)
                    expired.append(str(r["upload_ref"]))
        return expired
