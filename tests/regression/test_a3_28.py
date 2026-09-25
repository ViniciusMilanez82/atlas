"""A3-28 / T28: one owner per data directory; a second instance never deletes a live socket.

In-process lock semantics run everywhere; the real-process scenario (two atlas-core daemons on the same
directories, then an orphan socket after SIGKILL) needs Unix domain sockets and runs on the Linux/macOS
CI runners. The Supervisor side is covered by SupervisorTests on the macOS runner.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from core.instance_lock import InstanceBusy, InstanceLock

ROOT = Path(__file__).resolve().parents[2]


def test_second_lock_on_the_same_directory_is_refused(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path).acquire()
    with pytest.raises(InstanceBusy) as exc:
        InstanceLock(tmp_path).acquire()
    assert "another atlas-core" in str(exc.value)
    first.release()
    InstanceLock(tmp_path).acquire().release()  # released by the owner -> free again


@pytest.mark.skipif(
    not hasattr(os, "fork") or sys.platform == "win32", reason="atlas-core needs Unix sockets"
)
def test_two_daemons_one_owner_and_orphan_socket_recovery() -> None:
    import shutil
    import tempfile

    from tests.e2e.test_daemon_e2e import Daemon, dirs  # noqa: F401  (POSIX-only helpers)

    base = Path(tempfile.mkdtemp(prefix="atl", dir="/tmp"))
    data, ipc = base / "data", base / "ipc"
    try:
        first = Daemon(data, ipc, "http://127.0.0.1:9/v1", {})
        sock = json.loads((ipc / "session.json").read_text(encoding="utf-8"))["socket"]
        second = subprocess.run(  # before the fix: it unlinked the live socket and rewrote the token
            [sys.executable, "-m", "core", "--data-dir", str(data), "--ipc-dir", str(ipc)],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert second.returncode == 3, (second.stdout, second.stderr)
        assert "another atlas-core" in second.stdout
        assert Path(sock).exists()
        assert "result" in first.call("identity.get")  # the healthy owner still serves on its socket
        first.proc.send_signal(signal.SIGKILL)  # crash: socket and session files stay behind as orphans
        first.proc.wait(10)
        assert Path(sock).exists()
        third = Daemon(data, ipc, "http://127.0.0.1:9/v1", {})  # lock free -> orphan socket replaced
        assert "result" in third.call("identity.get")
        third.stop()
    finally:
        shutil.rmtree(base, ignore_errors=True)
