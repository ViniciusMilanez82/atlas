"""Disposable Python execution INSIDE the VM, with bubblewrap + seccomp + hard limits.

Generated code never runs in the trusted host. The guest service runs as the non-root atlas user.
Even in the guest, a job gets no browser profile, daemon sockets, network or persistent home.
"""
from __future__ import annotations

import base64
import hashlib
import os
import selectors
import signal
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from workspace_wire import MAX_FILE, MAX_FILES, MAX_OUTPUT, bounded_bytes, validate_command, validate_name

BWRAP = "/usr/bin/bwrap"
GUARD = "/usr/libexec/atlas-exec-guard"
_MARKER = Path("/etc/atlas-guest-image")


def sandbox_argv(work: Path, timeout: int) -> list[str]:
    # The mounts are constants, NEVER chosen by a model, manifest, skill or remote command.
    return [
        BWRAP, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/bin", "/bin",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/etc",  # noqa: S108 -- isolated guest mount
        "--dir", "/home", "--dir", "/home/runner", "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/home/runner",
        "--setenv", "LANG", "C.UTF-8", "--setenv", "PYTHONIOENCODING", "utf-8",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--bind", str(work), "/work", "--chdir", "/work",
        GUARD, str(timeout), "/usr/bin/python3", "-I", "-B", "/work/main.py",
    ]


class ExecutionBox:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, subprocess.Popen[bytes]] = {}
        self._cancelled: set[str] = set()
        self._seen: set[str] = set()
        self._capacity = threading.BoundedSemaphore(1)

    @staticmethod
    def available() -> bool:
        return _MARKER.is_file() and os.geteuid() != 0 and Path(BWRAP).is_file() and Path(GUARD).is_file()

    def cancel(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            if len(self._cancelled) >= 10000 and run_id not in self._jobs:
                raise RuntimeError("cancel receipt capacity reached; restart the isolated workspace")
            self._cancelled.add(run_id)
            proc = self._jobs.get(run_id)
            if proc is not None:
                self._kill(proc)
        return {"cancel_requested": True, "running": proc is not None}

    @staticmethod
    def _kill(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        validate_command("execution.run", args)
        if not self.available():
            raise RuntimeError("the isolated Linux appliance is required; no host execution fallback")
        if not self._capacity.acquire(blocking=False):
            raise RuntimeError("another execution is running in this workspace")
        run_id = args["run_id"]
        try:
            with self._lock:
                if run_id in self._seen or run_id in self._cancelled:
                    raise RuntimeError("execution id has already been used or cancelled; reconcile first")
                if len(self._seen) >= 10000:
                    raise RuntimeError("execution receipt capacity reached; restart the isolated workspace")
                self._seen.add(run_id)
            with tempfile.TemporaryDirectory(prefix="atlas-job-", dir="/tmp") as directory:
                work = Path(directory)
                (work / "main.py").write_text(args["code"], encoding="utf-8")
                (work / "output").mkdir(mode=0o700)
                for item in args["files"]:
                    (work / validate_name(item["name"])).write_bytes(bounded_bytes(item["data"]))
                proc = subprocess.Popen(sandbox_argv(work, args["timeout_s"]), stdin=subprocess.DEVNULL,  # noqa: S603 -- fixed guest-only argv, source written as data
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True, env={"PATH": "/usr/bin:/bin"}, close_fds=True)
                with self._lock:
                    self._jobs[run_id] = proc
                    if run_id in self._cancelled:
                        self._kill(proc)
                try:
                    stdout, stderr, limit = self._collect(proc, args["timeout_s"])
                finally:
                    self._kill(proc)
                    proc.wait(timeout=5)
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()
                    with self._lock:
                        self._jobs.pop(run_id, None)
                with self._lock:
                    cancelled = run_id in self._cancelled
                files, warnings = self._outputs(work / "output") if not cancelled else ([], [])
                return {"run_id": run_id, "exit_code": proc.returncode,
                        "stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace"),
                        "cancelled": cancelled, "limit": limit, "files": files, "warnings": warnings,
                        "network": "none", "isolation": "Linux VM / namespaces / seccomp / rlimits"}
        finally:
            self._capacity.release()

    @staticmethod
    def _collect(proc: subprocess.Popen[bytes], timeout: int) -> tuple[bytes, bytes, str | None]:
        deadline = time.monotonic() + timeout
        out = {"stdout": bytearray(), "stderr": bytearray()}
        limit = None
        with selectors.DefaultSelector() as sel:
            assert proc.stdout is not None and proc.stderr is not None
            for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
                os.set_blocking(stream.fileno(), False)
                sel.register(stream, selectors.EVENT_READ, name)
            while sel.get_map():
                if time.monotonic() >= deadline:
                    limit = "time"
                    ExecutionBox._kill(proc)
                    break
                for key, _ in sel.select(timeout=0.1):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    target = out[key.data]
                    available = MAX_OUTPUT - len(target)
                    target.extend(chunk[:available])
                    if len(chunk) > available:
                        limit = "output"
                        ExecutionBox._kill(proc)
                        return bytes(out["stdout"]), bytes(out["stderr"]), limit
        return bytes(out["stdout"]), bytes(out["stderr"]), limit

    @staticmethod
    def _outputs(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        total = 0
        # No recursion: a job cannot cause an unbounded walk or import a nested profile.
        for index, entry in enumerate(os.scandir(root)):
            if index >= MAX_FILES:
                warnings.append("more output entries exist than the transfer limit; remaining entries not imported")
                break
            try:
                name = validate_name(entry.name)
                fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    attrs = os.fstat(stream.fileno())
                    if not stat.S_ISREG(attrs.st_mode) or attrs.st_nlink != 1 or attrs.st_size > MAX_FILE:
                        raise ValueError("not a single-link bounded regular file")
                    raw = stream.read(MAX_FILE + 1)
                if len(raw) > MAX_FILE or total + len(raw) > MAX_FILE:
                    raise ValueError("output transfer limit exceeded")
                total += len(raw)
                results.append({"name": name, "data": base64.b64encode(raw).decode("ascii"),
                                "sha256": hashlib.sha256(raw).hexdigest()})
            except (ValueError, OSError):
                warnings.append("an output entry was refused (type, path or size); it was not imported")
        return results, warnings
