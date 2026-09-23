"""SQLite connection management (spec 4.4, 9.3, 13.3).

Durability choices: WAL journal, ``synchronous=FULL`` (a confirmed message must survive a crash),
foreign keys enforced, and explicit ``BEGIN IMMEDIATE`` transactions so that writers serialize
instead of failing half-way. Per ADR-012 only the atlas-core process opens write connections.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BUSY_TIMEOUT_MS = 5000


class StorageError(RuntimeError):
    pass


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with Atlas pragmas. ``path`` may be ``":memory:"`` for tests."""
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    if str(path) != ":memory:":
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise StorageError(f"could not enable WAL (got {mode!r})")
    conn.execute("PRAGMA synchronous = FULL")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise StorageError("foreign keys could not be enabled")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serializable write transaction. Rolls back on any exception.

    Nested use is rejected: callers compose operations inside a single transaction explicitly.
    """
    if conn.in_transaction:
        raise StorageError("nested transaction; compose inside the outer transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def require_transaction(conn: sqlite3.Connection) -> None:
    """Guard for functions that must run inside a caller-owned transaction."""
    if not conn.in_transaction:
        raise StorageError("this operation must run inside a transaction")
