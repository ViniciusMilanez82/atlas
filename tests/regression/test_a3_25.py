"""A3-25 / T32: reading an artifact in chunks costs ~linear I/O and still detects tampering.

Instrumented ArtifactManager counters (bytes hashed + bytes read) over the real artifacts.read handler.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from core.ipc.sessions import Session
from runtime.artifacts.manager import ArtifactManager
from tests.conftest import World

CHUNK = 512 * 1024


def _read_all(svc: Any, session: Session, artifact_id: str) -> bytes:
    out = bytearray()
    offset = 0
    while True:
        r = svc.handle(
            session,
            {
                "jsonrpc": "2.0",
                "id": "req-read-0001",
                "method": "artifacts.read",
                "params": {
                    "schema_version": "1.0",
                    "correlation_id": "corr-read-01",
                    "artifact_id": artifact_id,
                    "offset": offset,
                    "length": CHUNK,
                },
            },
        )
        assert "result" in r, r
        piece = base64.b64decode(r["result"]["data_b64"])
        out += piece
        offset += len(piece)
        if r["result"]["eof"]:
            return bytes(out)


@pytest.mark.parametrize("mib", [1, 10, 50])
def test_chunked_read_is_linear(env: Any, world: World, tmp_path: Path, mib: int) -> None:
    data = os.urandom(mib * 1024 * 1024)
    f = tmp_path / "grande.json"
    f.write_bytes(b'{"d": "' + base64.b64encode(data)[: len(data) - 10] + b'"}')
    svc = env.make()
    art = svc.artifacts.import_file(f, actor=world.owner, employee_id=world.employee.id)
    svc.artifacts.bytes_hashed = svc.artifacts.bytes_read = 0
    got = _read_all(svc, Session(world.owner, world.employee.id), art.id)
    assert hashlib.sha256(got).hexdigest() == art.sha256
    size = art.size_bytes
    io = svc.artifacts.bytes_hashed + svc.artifacts.bytes_read
    assert io <= 2 * size + CHUNK, f"{io} bytes of I/O for {size} bytes (quadratic before the fix)"


def test_tampering_during_a_chunked_read_is_refused(env: Any, world: World, tmp_path: Path) -> None:
    f = tmp_path / "doc.txt"
    f.write_bytes(b"a" * (3 * CHUNK))
    svc = env.make()
    art = svc.artifacts.import_file(f, actor=world.owner, employee_id=world.employee.id)
    session = Session(world.owner, world.employee.id)
    first = svc.handle(
        session,
        {
            "jsonrpc": "2.0",
            "id": "req-read-0002",
            "method": "artifacts.read",
            "params": {
                "schema_version": "1.0",
                "correlation_id": "corr-read-02",
                "artifact_id": art.id,
                "offset": 0,
                "length": CHUNK,
            },
        },
    )
    assert "result" in first
    obj = ArtifactManager(world.conn, world.clock, env.store_root)._object_path(art.sha256)
    obj.write_bytes(b"b" * (3 * CHUNK))  # the stored object changes behind the reader's back
    later = svc.handle(
        session,
        {
            "jsonrpc": "2.0",
            "id": "req-read-0003",
            "method": "artifacts.read",
            "params": {
                "schema_version": "1.0",
                "correlation_id": "corr-read-03",
                "artifact_id": art.id,
                "offset": CHUNK,
                "length": CHUNK,
            },
        },
    )
    assert later["error"]["data"]["atlas_code"] == "INVALID_INPUT" and "hash" in later["error"]["message"]
