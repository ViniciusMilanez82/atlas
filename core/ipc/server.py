"""IPC connection loop and Unix-socket server (spec 13.4; ADR-013).

First frame: ``{"hello": <session token>, "protocol": "1.0"}``. Anything else closes the connection.
Then JSON-RPC frames until EOF. Oversized or malformed frames close the connection. On POSIX the socket
lives in a 0700 directory and, where the OS supports it, the peer UID must equal ours.
"""

from __future__ import annotations

import os
import socket
import stat
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from core.ipc.framing import FrameError, recv_frame, send_frame
from core.ipc.sessions import SessionRegistry
from core.service import CoreService

PROTOCOL = "1.0"


def serve_connection(
    sock: socket.socket, sessions: SessionRegistry, service_factory: Callable[[], CoreService]
) -> None:
    try:
        hello = recv_frame(sock)
        session = sessions.resolve(hello.get("hello")) if hello.get("protocol") == PROTOCOL else None
        if session is None:
            send_frame(sock, {"hello": "rejected"})
            return
        send_frame(sock, {"hello": "ok", "protocol": PROTOCOL, "actor_kind": session.actor.kind})
        service = service_factory()
        while True:
            try:
                request = recv_frame(sock)
            except EOFError:
                return
            send_frame(sock, service.handle(session, request))
    except (FrameError, EOFError, OSError):
        return
    finally:
        sock.close()


def _peer_uid_ok(conn: socket.socket) -> bool:
    if sys.platform == "win32":  # no Unix domain sockets / UIDs on the Windows dev host
        return True
    if hasattr(socket, "SO_PEERCRED"):  # Linux
        import struct

        creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", creds)
        return bool(uid == os.getuid())
    if sys.platform == "darwin" and hasattr(os, "getuid"):
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        uid, gid = ctypes.c_uint32(), ctypes.c_uint32()
        if libc.getpeereid(conn.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            return False
        return bool(uid.value == os.getuid())
    return True  # no peer credential API: rely on the 0700 directory


class UnixSocketServer:
    """Serve IPC on a Unix Domain Socket inside a private directory. POSIX only."""

    def __init__(
        self, directory: Path, sessions: SessionRegistry, service_factory: Callable[[], CoreService]
    ):
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("Unix domain sockets are not available on this platform")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        if stat.S_IMODE(directory.stat().st_mode) != 0o700:
            raise PermissionError("IPC directory must be private (0700)")
        self.path = directory / "atlas-core.sock"
        if self.path.exists():
            self.path.unlink()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self.sock.listen(16)
        self.sessions = sessions
        self.factory = service_factory
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            if not _peer_uid_ok(conn):
                conn.close()
                continue
            threading.Thread(
                target=serve_connection, args=(conn, self.sessions, self.factory), daemon=True
            ).start()

    def close(self) -> None:
        self._stop.set()
        self.sock.close()
        if self.path.exists():
            self.path.unlink()
