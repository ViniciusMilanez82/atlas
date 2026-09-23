"""Open a migrated Atlas database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from shared.clock import Clock
from storage.db import connect
from storage.migrate import migrate


def open_store(path: Path | str, clock: Clock | None = None) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn, clock=clock)
    return conn
