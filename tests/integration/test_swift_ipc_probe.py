"""Etapa 4 (partial): the compiled Swift client (platform/macos/AtlasKit) talks to the Python core over
the Unix socket. Runs on the macOS CI runner after `swift build`; elsewhere it is NOT EXECUTED.

Proves the cross-language IPC contract (framing, handshake, session identity, rejection of a forged
actor field). It does NOT prove the interactive app or the owner's Mac.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

from core.ipc.server import UnixSocketServer
from core.ipc.sessions import SessionRegistry
from tests.conftest import World
from tests.integration.test_ipc import factory


@pytest.mark.macos
def test_swift_client_talks_to_python_core(world: World) -> None:
    probe = os.environ.get("ATLAS_SWIFT_PROBE")
    if not probe or not Path(probe).is_file():
        pytest.skip("NAO EXECUTADO: build platform/macos/AtlasKit and set ATLAS_SWIFT_PROBE")
    short = Path(tempfile.mkdtemp(prefix="atl", dir="/tmp"))
    sessions = SessionRegistry()
    server = UnixSocketServer(short / "ipc", sessions, factory(world))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    token_file = short / "token"
    token_file.write_text(sessions.issue(world.owner, world.employee.id), encoding="utf-8")
    os.chmod(token_file, 0o600)
    try:
        proc = subprocess.run(
            [probe, str(server.path), str(token_file), world.employee.id],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["health"]["result"]["status"] == "ok"
        task = out["created"]["result"]["task"]
        assert task["state"] == "CREATED"
        row = world.conn.execute("SELECT objective FROM tasks WHERE id = ?", (task["task_id"],)).fetchone()
        assert row[0] == "Tarefa criada pelo cliente Swift"  # really persisted by the Python core
        assert out["forged"]["error"]["data"]["atlas_code"] == "INVALID_INPUT"  # body cannot carry an actor
    finally:
        server.close()
        shutil.rmtree(short, ignore_errors=True)
