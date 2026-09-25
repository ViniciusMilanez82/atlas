"""Single owner of a data directory (A3-28, spec 22.2; scenario T28).

The lock is taken BEFORE anything shared is touched (database recovery, session token, IPC socket), so
a second atlas-core on the same data directory stops with a diagnostic instead of deleting the live
socket or running a second recovery. The OS releases the lock when the process dies, which is how an
orphan socket (left by a crash) is told apart from a live one: if we hold the lock, nobody is serving it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import IO


class InstanceBusy(RuntimeError):
    def __init__(self, path: Path, holder: str) -> None:
        super().__init__(f"another atlas-core owns {path.parent} (holder: {holder or 'unknown'})")
        self.holder = holder


class InstanceLock:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "atlas-core.lock"
        self._fh: IO[str] | None = None

    def acquire(self) -> InstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+", encoding="utf-8")
        try:
            if sys.platform == "win32":  # development host only; the product runs on macOS
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                fh.seek(0)
                holder = fh.read().strip()
            except OSError:
                holder = ""
            fh.close()
            raise InstanceBusy(self.path, holder) from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()}\n")
        fh.flush()
        self._fh = fh
        return self

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()  # closing the descriptor releases the OS lock
            self._fh = None

    def __enter__(self) -> InstanceLock:
        return self.acquire()

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.release()
