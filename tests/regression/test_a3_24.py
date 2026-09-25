"""A3-24 / T14 (+ A3-22 import receipt, T15): uploads are coordinated across connections, bounded by
quota and TTL, finalized once, and a lost import reply is recovered instead of duplicated.

Real IPC over socket pairs; every connection has its own CoreService and SQLite connection, exactly
like the daemon.
"""

from __future__ import annotations

import base64
import hashlib
import threading
from typing import Any

from runtime.artifacts.uploads import UploadSweeper
from shared.ids import new_id
from tests.conftest import World
from tests.integration.test_alpha2 import ok


def _chunk(c: Any, ref: str, offset: int, data: bytes) -> dict[str, Any]:
    return c.call("artifacts.upload", upload_ref=ref, offset=offset, data_b64=base64.b64encode(data).decode())


def _import(c: Any, world: World, ref: str, name: str = "dados.txt", **kw: Any) -> dict[str, Any]:
    return c.call("artifacts.import", employee_id=world.employee.id, upload_ref=ref, declared_name=name, **kw)


def test_same_chunk_from_two_connections_is_written_once(env: Any, world: World) -> None:
    c1, c2 = env.connect(), env.connect()
    ref = new_id()
    part1, part2 = b"A" * 300_000, b"B" * 200_000
    barrier = threading.Barrier(2)
    results: list[dict[str, Any]] = []

    def race(c: Any) -> None:
        barrier.wait()
        results.append(_chunk(c, ref, 0, part1))

    threads = [threading.Thread(target=race, args=(c,)) for c in (c1, c2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all("result" in r for r in results), results
    assert sorted(r["result"]["duplicate"] for r in results) == [False, True]
    ok(_chunk(c2, ref, len(part1), part2))
    art = ok(_import(c1, world, ref, expected_sha256=hashlib.sha256(part1 + part2).hexdigest()))
    assert art["size_bytes"] == len(part1) + len(part2)  # before the fix: bytes could be appended twice
    assert art["sha256"] == hashlib.sha256(part1 + part2).hexdigest()


def test_lost_import_reply_returns_the_same_artifact(env: Any, world: World) -> None:
    c = env.connect()
    ref = new_id()
    ok(_chunk(c, ref, 0, b"conteudo sintetico"))
    first = ok(_import(c, world, ref))
    c2 = env.connect()  # the reply was lost; the app reconnects and asks again with the same upload_ref
    again = ok(_import(c2, world, ref))
    assert again["artifact_id"] == first["artifact_id"] and again["recovered"] is True
    assert (
        world.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
    )  # before: 'upload not found'


def test_interrupted_upload_resumes_on_a_new_connection(env: Any, world: World) -> None:
    c = env.connect()
    ref = new_id()
    ok(_chunk(c, ref, 0, b"x" * 1000))
    c.sock.close()  # the app died mid-upload
    c2 = env.connect()
    resp = _chunk(c2, ref, 0, b"y" * 1000)  # different bytes at the same offset
    assert resp["error"]["data"]["atlas_code"] == "VERSION_CONFLICT"
    ok(_chunk(c2, ref, 1000, b"x" * 24))
    assert ok(_import(c2, world, ref))["size_bytes"] == 1024


def test_expired_staging_is_removed_but_active_uploads_are_kept(env: Any, world: World) -> None:
    c = env.connect()
    old, fresh = new_id(), new_id()
    ok(_chunk(c, old, 0, b"velho"))
    world.clock.advance(hours=2)
    ok(_chunk(c, fresh, 0, b"novo"))
    swept = UploadSweeper(world.conn, world.clock, env.store_root).sweep()
    assert swept == [old]
    assert "error" in _import(c, world, old)  # expired: must be sent again
    assert ok(_import(c, world, fresh))["size_bytes"] == 4


def test_aggregate_staging_quota_is_enforced(env: Any, world: World, monkeypatch: Any) -> None:
    import runtime.artifacts.uploads as uploads

    monkeypatch.setattr(uploads, "MAX_STAGING_BYTES_PER_EMPLOYEE", 1_500)
    c = env.connect()
    ok(_chunk(c, new_id(), 0, b"a" * 1_000))
    resp = _chunk(c, new_id(), 0, b"b" * 1_000)
    assert resp["error"]["data"]["atlas_code"] == "INVALID_INPUT" and "quota" in resp["error"]["message"]


def test_import_hash_mismatch_is_refused(env: Any, world: World) -> None:
    c = env.connect()
    ref = new_id()
    ok(_chunk(c, ref, 0, b"abc"))
    resp = _import(c, world, ref, expected_sha256="0" * 64)
    assert resp["error"]["data"]["atlas_code"] == "INVALID_INPUT"
    assert world.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
