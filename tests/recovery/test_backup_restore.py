"""AT-005.5 / GA-15 (backup part): verified restore that cannot repeat external effects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from storage.backup.backup import create_backup, restore_backup, verify_backup
from storage.db import StorageError, transaction
from storage.migrate import discover
from storage.store import open_store
from tests.conftest import World
from tests.helpers import insert_action, insert_approval, insert_mandate, insert_task


def populate(world: World) -> dict[str, str]:
    c = world.conn
    with transaction(c):
        t_running = insert_task(c, world.owner_id, world.employee.id, state="READY")
        c.execute(
            "UPDATE tasks SET state='RUNNING', lease_owner='w1', lease_expires_at='2026-01-01T00:05:00.000Z',"
            " fencing_token=3 WHERE id=?",
            (t_running,),
        )
        a_dispatching = insert_action(c, t_running, status="DISPATCHING")
        a_authorized = insert_action(c, t_running, status="AUTHORIZED")
        a_confirmed = insert_action(c, t_running, status="CONFIRMED")
        ap = insert_approval(c, t_running, a_authorized, status="APPROVED")
        md = insert_mandate(c, world.owner_id, world.employee.id)
    return {
        "task": t_running,
        "dispatching": a_dispatching,
        "authorized": a_authorized,
        "confirmed": a_confirmed,
        "approval": ap,
        "mandate": md,
    }


def test_backup_restore_round_trip_neutralizes_authority(world: World, tmp_path: Path) -> None:
    ids = populate(world)
    manifest = create_backup(world.conn, tmp_path / "bk1", world.clock)
    assert manifest["schema_version"] == len(discover())
    assert manifest["encrypted"] is False  # documented limitation T-12

    # State diverges after the backup.
    with transaction(world.conn):
        world.conn.execute("DELETE FROM mandates")
    world.conn.close()

    report = restore_backup(tmp_path / "bk1", world.path, world.clock)
    assert (report.revoked_approvals, report.revoked_mandates) == (1, 1)
    assert (report.cancelled_actions, report.unknown_actions) == (1, 1)

    conn = open_store(world.path, world.clock)
    try:
        status = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM actions").fetchall()}
        assert status[ids["dispatching"]] == "UNKNOWN"
        assert status[ids["authorized"]] == "CANCELLED_BEFORE_DISPATCH"
        assert status[ids["confirmed"]] == "CONFIRMED"
        assert conn.execute("SELECT status FROM approvals").fetchone()[0] == "REVOKED"
        assert conn.execute("SELECT status FROM mandates").fetchone()[0] == "REVOKED"
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (ids["task"],)).fetchone()
        assert task["state"] == "BLOCKED"
        assert task["blocked_reason"] == "EXTERNAL_EFFECT_UNKNOWN"
        assert task["lease_owner"] is None
        assert task["fencing_token"] == 4
        types = [r[0] for r in conn.execute("SELECT type FROM journal_events")]
        assert "backup.restored" in types
    finally:
        conn.close()
    world.conn = open_store(world.path, world.clock)  # fixture teardown closes it


def test_tampered_backup_is_refused(world: World, tmp_path: Path) -> None:
    create_backup(world.conn, tmp_path / "bk", world.clock)
    db = tmp_path / "bk" / "atlas.sqlite"
    data = bytearray(db.read_bytes())
    data[-100] ^= 0xFF
    db.write_bytes(bytes(data))
    with pytest.raises(StorageError, match="hash mismatch"):
        verify_backup(tmp_path / "bk")


def test_manifest_row_count_mismatch_is_refused(world: World, tmp_path: Path) -> None:
    create_backup(world.conn, tmp_path / "bk", world.clock)
    mf = tmp_path / "bk" / "manifest.json"
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    manifest["row_counts"]["journal_events"] += 1
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(StorageError, match="row count mismatch"):
        verify_backup(tmp_path / "bk")


def test_backup_from_newer_build_is_refused(world: World, tmp_path: Path) -> None:
    create_backup(world.conn, tmp_path / "bk", world.clock)
    mf = tmp_path / "bk" / "manifest.json"
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    manifest["schema_version"] = 99
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(StorageError, match="newer build"):
        verify_backup(tmp_path / "bk")


def test_incomplete_backup_is_refused(tmp_path: Path) -> None:
    (tmp_path / "bk").mkdir()
    with pytest.raises(StorageError, match="incomplete"):
        verify_backup(tmp_path / "bk")


def test_backup_directory_must_be_new(world: World, tmp_path: Path) -> None:
    (tmp_path / "exists").mkdir()
    with pytest.raises(FileExistsError):
        create_backup(world.conn, tmp_path / "exists", world.clock)


# --- encrypted backups (THREAT_MODEL T-12, backup part) ------------------------------------------


def test_encrypted_backup_round_trip_and_no_plaintext_on_disk(world: World, tmp_path: Path) -> None:
    import os

    from storage.migrate import discover

    key = os.urandom(32)
    with transaction(world.conn):
        world.conn.execute(
            "INSERT INTO owners VALUES ('marcador-sintetico-owner', 'Marcador Unico XYZ', '2026-01-01T00:00:00.000Z')"
        )
    manifest = create_backup(world.conn, tmp_path / "bk", world.clock, key=key)
    assert manifest["encrypted"] is True and manifest["cipher"] == "AES-256-GCM"
    files = sorted(p.name for p in (tmp_path / "bk").iterdir())
    assert files == ["atlas.sqlite.enc", "manifest.json"]  # no plaintext copy left behind
    assert b"Marcador Unico XYZ" not in (tmp_path / "bk" / "atlas.sqlite.enc").read_bytes()
    verify_backup(tmp_path / "bk", key)
    world.conn.close()
    restore_backup(tmp_path / "bk", world.path, world.clock, key=key)
    world.conn = open_store(world.path, world.clock)
    assert (
        world.conn.execute("SELECT display_name FROM owners WHERE id='marcador-sintetico-owner'").fetchone()[
            0
        ]
        == "Marcador Unico XYZ"
    )
    assert len(discover()) >= 1


def test_encrypted_backup_needs_the_right_key(world: World, tmp_path: Path) -> None:
    import os

    key = os.urandom(32)
    create_backup(world.conn, tmp_path / "bk", world.clock, key=key)
    with pytest.raises(StorageError, match="key is required"):
        verify_backup(tmp_path / "bk")
    with pytest.raises(StorageError, match="cannot be decrypted"):
        verify_backup(tmp_path / "bk", os.urandom(32))


def test_encrypted_backup_tampering_is_detected(world: World, tmp_path: Path) -> None:
    import os

    key = os.urandom(32)
    manifest = create_backup(world.conn, tmp_path / "bk", world.clock, key=key)
    enc = tmp_path / "bk" / "atlas.sqlite.enc"
    data = bytearray(enc.read_bytes())
    data[40] ^= 0x01
    enc.write_bytes(bytes(data))
    with pytest.raises(StorageError, match="hash mismatch"):
        verify_backup(tmp_path / "bk", key)
    # Even if an attacker also rewrites the manifest hash, authenticated encryption refuses it.
    mf = tmp_path / "bk" / "manifest.json"
    m = json.loads(mf.read_text(encoding="utf-8"))
    import hashlib

    m["sha256"] = hashlib.sha256(bytes(data)).hexdigest()
    mf.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(StorageError, match="cannot be decrypted"):
        verify_backup(tmp_path / "bk", key)
    assert manifest["encrypted"] is True


def test_backup_key_must_be_256_bits(world: World, tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="32 bytes"):
        create_backup(world.conn, tmp_path / "bk", world.clock, key=b"short")
