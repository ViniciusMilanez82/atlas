"""Bounded null-delimited DevTools pipe; never binds a TCP/debugging port."""
from __future__ import annotations

import os
import select
import threading
import time

MAX_MESSAGE = 1024 * 1024


class CDPPipe:
    def __init__(self, reader: int, writer: int) -> None:
        self.reader, self.writer = reader, writer
        os.set_blocking(reader, False)
        os.set_blocking(writer, False)
        self.pending = bytearray()
        self._closed = False
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for fd in (self.reader, self.writer):
                try:
                    os.close(fd)
                except OSError:
                    continue

    def send(self, content: str) -> None:
        raw = content.encode("utf-8") + b"\0"
        if len(raw) > MAX_MESSAGE or b"\0" in raw[:-1]:
            raise ValueError("DevTools request exceeds bound")
        deadline = time.monotonic() + 3
        offset = 0
        while offset < len(raw):
            with self._lock:
                if self._closed:
                    raise EOFError("DevTools pipe was closed")
                try:
                    offset += os.write(self.writer, raw[offset:])
                except BlockingIOError:
                    pass
            if offset < len(raw):
                if time.monotonic() >= deadline:
                    raise TimeoutError("DevTools write timed out")
                time.sleep(0.01)

    def recv(self) -> str:
        until = time.monotonic() + 0.25
        while True:
            if b"\0" in self.pending:
                raw, _, rest = self.pending.partition(b"\0")
                self.pending = bytearray(rest)
                if len(raw) > MAX_MESSAGE:
                    raise ValueError("DevTools message exceeds bound")
                return raw.decode("utf-8")
            if len(self.pending) > MAX_MESSAGE:
                raise ValueError("DevTools message exceeds bound")
            if time.monotonic() >= until:
                raise TimeoutError("DevTools read would block")
            with self._lock:
                if self._closed:
                    raise EOFError("DevTools pipe closed")
                if select.select([self.reader], [], [], 0)[0]:
                    block = os.read(self.reader, 65536)
                    if not block:
                        raise EOFError("Chromium closed DevTools")
                    self.pending.extend(block)
            time.sleep(0.005)
