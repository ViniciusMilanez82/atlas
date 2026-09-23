"""AT-005.4: a process killed before or after COMMIT never leaves an invalid state.

A child process is terminated with ``os._exit`` (no cleanup, no rollback) at the chosen point.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from storage.store import open_store

ROOT = Path(__file__).resolve().parents[2]

CHILD = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, {root!r})
    from storage.db import connect
    conn = connect({db!r})
    conn.execute("BEGIN IMMEDIATE")
    for i in range(50):
        conn.execute("INSERT INTO owners(id, display_name, created_at) VALUES (?, ?, ?)",
                     ("crash-%03d" % i, "sintetico", "2026-01-01T00:00:00.000Z"))
    if {commit}:
        conn.execute("COMMIT")
    os._exit(9)
    """
)


def run_child(db: Path, commit: bool) -> int:
    code = CHILD.format(root=str(ROOT), db=str(db), commit=commit)
    return subprocess.run([sys.executable, "-c", code], check=False).returncode


@pytest.mark.parametrize(("commit", "expected"), [(False, 0), (True, 50)])
def test_kill_before_or_after_commit(tmp_path: Path, commit: bool, expected: int) -> None:
    db = tmp_path / "atlas.sqlite"
    open_store(db).close()
    assert run_child(db, commit) == 9
    conn = open_store(db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        n = conn.execute("SELECT COUNT(*) FROM owners WHERE id LIKE 'crash-%'").fetchone()[0]
        assert n == expected, "partial transaction became visible" if not commit else "committed rows lost"
    finally:
        conn.close()
