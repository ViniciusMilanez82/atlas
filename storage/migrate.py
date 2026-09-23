"""Versioned, checksummed schema migrations (spec 13.3, 16.4).

Each ``storage/migrations/NNNN_name.sql`` runs once, inside one transaction, and is recorded with
its SHA-256. A previously applied migration whose file changed is a hard error: history must not
be rewritten silently.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from shared.clock import Clock, SystemClock, to_utc_str
from storage.db import StorageError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        m = _NAME.match(path.name)
        if not m:
            raise StorageError(f"bad migration file name: {path.name}")
        found.append(Migration(int(m.group(1)), m.group(2), path.read_text(encoding="utf-8")))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise StorageError(f"migration versions must be contiguous from 1: {versions}")
    return found


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL,"
        " applied_at TEXT NOT NULL) STRICT"
    )


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_table(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def migrate(
    conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR, clock: Clock | None = None
) -> list[int]:
    """Apply pending migrations. Returns the versions applied in this call."""
    clock = clock or SystemClock()
    migrations = discover(directory)
    _ensure_table(conn)
    applied = {
        int(r["version"]): str(r["checksum"])
        for r in conn.execute("SELECT version, checksum FROM schema_migrations")
    }
    for mig in migrations:
        if mig.version in applied and applied[mig.version] != mig.checksum:
            raise StorageError(f"migration {mig.version:04d} changed after being applied")
    if applied and max(applied) > len(migrations):
        raise StorageError("database schema is newer than this build; refusing to open")
    done: list[int] = []
    for mig in migrations:
        if mig.version in applied:
            continue
        script = (
            "BEGIN IMMEDIATE;\n"
            + mig.sql
            + "\nINSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES ("
            + f"{mig.version}, '{mig.name}', '{mig.checksum}', '{to_utc_str(clock.now())}');\n"
            + "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise StorageError(f"migration {mig.version:04d} failed: {exc}") from exc
        done.append(mig.version)
    return done
