"""Consistent backup and verified restore (spec 12.4, 16.3, AT-005.5).

Backup: SQLite online backup API into a fresh file + ``manifest.json`` with SHA-256, schema
version, row counts and creation time. Restore: verify the manifest and hash, run
``PRAGMA integrity_check``, swap the file atomically, then neutralize anything that could repeat
an external effect: approvals APPROVED/RESERVED -> REVOKED, active mandates -> REVOKED,
AUTHORIZED actions -> CANCELLED_BEFORE_DISPATCH, DISPATCHING actions -> UNKNOWN (the effect may
have happened after the backup was taken), and all task leases dropped.

Limitation (THREAT_MODEL T-12): backup files are not encrypted yet.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.actors import SYSTEM
from shared.clock import Clock, to_utc_str
from storage import journal
from storage.db import StorageError, connect, transaction
from storage.migrate import current_version, discover

DB_NAME = "atlas.sqlite"
MANIFEST = "manifest.json"
COUNTED_TABLES = (
    "tasks",
    "actions",
    "approvals",
    "memories",
    "memory_versions",
    "journal_events",
    "artifacts",
)


@dataclass(frozen=True)
class RestoreReport:
    schema_version: int
    revoked_approvals: int
    revoked_mandates: int
    cancelled_actions: int
    unknown_actions: int
    released_leases: int


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


ENC_NAME = "atlas.sqlite.enc"
_AAD = b"atlas-backup-1"


def _encrypt_file(plain: Path, key: bytes) -> bytes:
    """AES-256-GCM with a random 96-bit nonce (library: cryptography, audited). Returns nonce+ciphertext."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(key) != 32:
        raise StorageError("backup key must be 32 bytes (AES-256)")
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plain.read_bytes(), _AAD)


def _decrypt(blob: bytes, key: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], _AAD)
    except (InvalidTag, ValueError):
        raise StorageError("backup cannot be decrypted: wrong key or modified file") from None


def create_backup(
    conn: sqlite3.Connection, dest_dir: Path, clock: Clock, key: bytes | None = None
) -> dict[str, Any]:
    """Consistent backup. With ``key`` the database copy is encrypted (AES-256-GCM) and the plaintext
    copy is removed. Losing the key makes the backup unrecoverable - the UI must say so."""
    dest_dir.mkdir(parents=True, exist_ok=False)
    target = dest_dir / DB_NAME
    out = sqlite3.connect(str(target))
    try:
        conn.backup(out)
        out.execute("PRAGMA journal_mode = DELETE")  # self-contained single file
    finally:
        out.close()
    counts = {t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in COUNTED_TABLES}  # noqa: S608
    manifest: dict[str, Any] = {
        "format": "atlas-backup-1",
        "created_at": to_utc_str(clock.now()),
        "schema_version": current_version(conn),
        "row_counts": counts,
        "encrypted": key is not None,
    }
    if key is not None:
        enc = dest_dir / ENC_NAME
        enc.write_bytes(_encrypt_file(target, key))
        target.unlink()  # note: SSD wear-levelling may retain old blocks; FileVault covers the disk
        manifest.update({"cipher": "AES-256-GCM", "sha256": _sha256(enc), "size_bytes": enc.stat().st_size})
    else:
        manifest.update({"sha256": _sha256(target), "size_bytes": target.stat().st_size})
    (dest_dir / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _plain_bytes(backup_dir: Path, manifest: dict[str, Any], key: bytes | None) -> bytes:
    if manifest.get("encrypted"):
        if key is None:
            raise StorageError("backup is encrypted; the backup key is required")
        return _decrypt((backup_dir / ENC_NAME).read_bytes(), key)
    return (backup_dir / DB_NAME).read_bytes()


def verify_backup(backup_dir: Path, key: bytes | None = None) -> dict[str, Any]:
    manifest_path = backup_dir / MANIFEST
    if not manifest_path.is_file():
        raise StorageError("backup is incomplete (manifest or database missing)")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    data_file = backup_dir / (ENC_NAME if manifest.get("encrypted") else DB_NAME)
    if not data_file.is_file():
        raise StorageError("backup is incomplete (manifest or database missing)")
    if manifest.get("format") != "atlas-backup-1":
        raise StorageError("unknown backup format")
    if _sha256(data_file) != manifest["sha256"]:
        raise StorageError("backup hash mismatch: file is corrupt or was modified")
    if manifest["schema_version"] > len(discover()):
        raise StorageError("backup was made by a newer build; refusing to restore")
    plain = _plain_bytes(backup_dir, manifest, key)
    import tempfile

    fd, tmp_name = tempfile.mkstemp(prefix="atlas-verify-", suffix=".sqlite")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(plain)
        probe = sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True)
        try:
            result = probe.execute("PRAGMA integrity_check").fetchone()[0]
            for table, expected in manifest["row_counts"].items():
                got = probe.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                if got != expected:
                    raise StorageError(f"row count mismatch in {table}: {got} != {expected}")
        finally:
            probe.close()
    finally:
        tmp.unlink(missing_ok=True)
    if result != "ok":
        raise StorageError(f"integrity_check failed: {result}")
    return manifest


def restore_backup(
    backup_dir: Path, target_db: Path, clock: Clock, key: bytes | None = None
) -> RestoreReport:
    """Replace ``target_db`` with the verified backup. The target must not be open elsewhere."""
    manifest = verify_backup(backup_dir, key)
    staging = target_db.with_suffix(".restoring")
    staging.write_bytes(_plain_bytes(backup_dir, manifest, key))
    for suffix in ("-wal", "-shm"):
        side = Path(str(target_db) + suffix)
        if side.exists():
            side.unlink()
    os.replace(staging, target_db)

    conn = connect(target_db)
    try:
        from storage.migrate import migrate

        migrate(conn, clock=clock)
        now = to_utc_str(clock.now())
        with transaction(conn):
            a = conn.execute(
                "UPDATE approvals SET status = 'REVOKED', decided_at = ?"
                " WHERE status IN ('APPROVED','RESERVED','PENDING')",
                (now,),
            ).rowcount
            m = conn.execute(
                "UPDATE mandates SET status = 'REVOKED', revoked_at = ? WHERE status = 'ACTIVE'", (now,)
            ).rowcount
            c = conn.execute(
                "UPDATE actions SET status = 'CANCELLED_BEFORE_DISPATCH',"
                " status_reason = 'RESTORED_FROM_BACKUP', updated_at = ?"
                " WHERE status IN ('PROPOSED','AUTHORIZED')",
                (now,),
            ).rowcount
            u_rows = conn.execute("SELECT id, task_id FROM actions WHERE status = 'DISPATCHING'").fetchall()
            conn.execute(
                "UPDATE actions SET status = 'UNKNOWN', status_reason = 'RESTORED_FROM_BACKUP',"
                " updated_at = ? WHERE status = 'DISPATCHING'",
                (now,),
            )
            leases = conn.execute(
                "UPDATE tasks SET lease_owner = NULL, lease_expires_at = NULL,"
                " fencing_token = fencing_token + 1,"
                " state = CASE WHEN state = 'RUNNING' THEN 'PAUSED' ELSE state END,"
                " paused_from = CASE WHEN state = 'RUNNING' THEN 'RUNNING' ELSE paused_from END,"
                " version = version + 1,"
                " updated_at = ? WHERE lease_owner IS NOT NULL OR state = 'RUNNING'",
                (now,),
            ).rowcount
            for r in u_rows:
                conn.execute(
                    "UPDATE tasks SET state = 'BLOCKED', blocked_reason = 'EXTERNAL_EFFECT_UNKNOWN', paused_from = NULL,"
                    " version = version + 1, updated_at = ? WHERE id = ? AND state NOT IN"
                    " ('COMPLETED','FAILED','CANCELLED')",
                    (now, r["task_id"]),
                )
            for emp in conn.execute("SELECT id FROM employees").fetchall():
                journal.append(
                    conn,
                    clock,
                    employee_id=emp["id"],
                    type="backup.restored",
                    actor=SYSTEM,
                    summary=(
                        f"restore: revoked {a} approvals and {m} mandates,"
                        f" cancelled {c} undispatched actions,"
                        f" {len(u_rows)} in-flight actions set UNKNOWN, {leases} leases released"
                    ),
                )
        version = current_version(conn)
    finally:
        conn.close()
    return RestoreReport(version, a, m, c, len(u_rows), leases)
