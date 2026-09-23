"""Length-prefixed JSON framing for local IPC (spec 13.4): 4-byte big-endian length, max 1 MiB.

The length is checked before the body is read, so an oversized frame cannot exhaust memory.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any

MAX_FRAME = 1024 * 1024
_HEADER = struct.Struct(">I")


class FrameError(Exception):
    pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("peer closed the connection")
        buf.extend(chunk)
    return bytes(buf)


def send_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FRAME:
        raise FrameError("frame exceeds 1 MiB")
    sock.sendall(_HEADER.pack(len(data)) + data)


def recv_frame(sock: socket.socket) -> dict[str, Any]:
    (length,) = _HEADER.unpack(_recv_exact(sock, _HEADER.size))
    if length > MAX_FRAME:
        raise FrameError(f"frame of {length} bytes exceeds the 1 MiB limit")
    raw = _recv_exact(sock, length)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameError("frame is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise FrameError("frame must be a JSON object")
    return value
