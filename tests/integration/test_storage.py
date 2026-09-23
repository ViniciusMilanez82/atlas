"""AT-005.1..3: database, migrations, constraints and journal."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from shared.actors import Actor
from shared.clock import ManualClock
from shared.ids import new_id
from storage import journal
from storage.db import StorageError, connect, require_transaction, transaction
from storage.migrate import MIGRATIONS_DIR, current_version, discover, migrate
from tests.conftest import World
from tests.helpers import NOW, insert_action, insert_approval, insert_task


class TestMigrations:
    def test_applies_once_and_records_checksum(self, tmp_path: Path, clock: ManualClock) -> None:
        conn = connect(tmp_path / "a.sqlite")
        assert migrate(conn, clock=clock) == list(range(1, len(discover()) + 1))
        assert migrate(conn, clock=clock) == []
        row = conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY version").fetchone()
        assert row["version"] == 1
        assert row["checksum"] == discover()[0].checksum

    def test_tampered_applied_migration_is_rejected(self, tmp_path: Path, clock: ManualClock) -> None:
        mig_dir = tmp_path / "migs"
        shutil.copytree(MIGRATIONS_DIR, mig_dir)
        conn = connect(tmp_path / "a.sqlite")
        migrate(conn, mig_dir, clock)
        f = mig_dir / "0001_initial.sql"
        f.write_text(f.read_text(encoding="utf-8") + "\n-- edited later\n", encoding="utf-8")
        with pytest.raises(StorageError, match="changed after being applied"):
            migrate(conn, mig_dir, clock)

    def test_newer_database_is_refused(self, tmp_path: Path, clock: ManualClock) -> None:
        conn = connect(tmp_path / "a.sqlite")
        migrate(conn, clock=clock)
        conn.execute("INSERT INTO schema_migrations VALUES (99, 'future', 'x', ?)", (NOW,))
        with pytest.raises(StorageError, match="newer than this build"):
            migrate(conn, clock=clock)

    def test_failed_migration_leaves_no_partial_schema(self, tmp_path: Path, clock: ManualClock) -> None:
        mig_dir = tmp_path / "migs"
        mig_dir.mkdir()
        (mig_dir / "0001_bad.sql").write_text(
            "CREATE TABLE ok_table(x INTEGER) STRICT;\nCREATE TABLE broken(;\n", encoding="utf-8"
        )
        conn = connect(tmp_path / "a.sqlite")
        with pytest.raises(StorageError):
            migrate(conn, mig_dir, clock)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "ok_table" not in names
        assert current_version(conn) == 0


class TestConnection:
    def test_pragmas(self, world: World) -> None:
        c = world.conn
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL

    def test_fts5_available(self, world: World) -> None:
        with transaction(world.conn):
            world.conn.execute(
                "INSERT INTO memory_fts(content, memory_id) VALUES ('Reunião às terças', 'm1')"
            )
        rows = world.conn.execute(
            "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH 'reuniao'"
        ).fetchall()
        assert [r[0] for r in rows] == ["m1"]

    def test_nested_transaction_rejected(self, world: World) -> None:
        with transaction(world.conn), pytest.raises(StorageError), transaction(world.conn):
            pass

    def test_require_transaction(self, world: World) -> None:
        with pytest.raises(StorageError):
            require_transaction(world.conn)

    def test_rollback_on_exception(self, world: World) -> None:
        with pytest.raises(RuntimeError), transaction(world.conn):
            world.conn.execute("INSERT INTO owners VALUES (?, 'x', ?)", (new_id(), NOW))
            raise RuntimeError("boom")
        assert world.conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 1


class TestConstraints:
    """Spec 13.2: relations prevent actions without task, approvals without action and deliveries
    without an existing artifact."""

    def test_action_without_task_fails(self, world: World) -> None:
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            insert_action(world.conn, new_id())

    def test_approval_without_action_fails(self, world: World) -> None:
        with transaction(world.conn):
            tid = insert_task(world.conn, world.owner_id, world.employee.id)
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            insert_approval(world.conn, tid, new_id())

    def test_delivery_without_artifact_fails(self, world: World) -> None:
        with transaction(world.conn):
            tid = insert_task(world.conn, world.owner_id, world.employee.id)
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            world.conn.execute(
                "INSERT INTO deliveries(id, task_id, artifact_id, channel, status, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (new_id(), tid, new_id(), "owner", "PENDING", NOW),
            )

    def test_blocked_requires_reason(self, world: World) -> None:
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            insert_task(world.conn, world.owner_id, world.employee.id, state="BLOCKED")

    def test_invalid_enum_rejected(self, world: World) -> None:
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            insert_task(world.conn, world.owner_id, world.employee.id, state="DONE")

    def test_strict_types(self, world: World) -> None:
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            world.conn.execute(
                "INSERT INTO budget_reservations(id, category, period_key, amount_minor, currency, status,"
                " created_at) VALUES (?,?,?,?,?,?,?)",
                (new_id(), "inference", "2026-01", "cem", "USD", "RESERVED", NOW),
            )

    def test_money_needs_currency(self, world: World) -> None:
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            world.conn.execute(
                "INSERT INTO tasks(id, owner_id, employee_id, objective, constraints_json, priority,"
                " data_policy, budget_amount_minor, state, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    world.owner_id,
                    world.employee.id,
                    "x",
                    "{}",
                    "NORMAL",
                    "INTERNAL",
                    100,
                    "CREATED",
                    NOW,
                    NOW,
                ),
            )

    def test_r5_approval_cannot_be_stored(self, world: World) -> None:
        with transaction(world.conn):
            tid = insert_task(world.conn, world.owner_id, world.employee.id)
            aid = insert_action(world.conn, tid)
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            world.conn.execute(
                "INSERT INTO approvals(id, task_id, action_id, requested_by, action_type, destination,"
                " params_hash, recurrence, expires_at, max_uses, policy_version, risk_class, status, nonce,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    tid,
                    aid,
                    "runtime",
                    "x.y",
                    "d",
                    "a" * 64,
                    "ONCE",
                    NOW,
                    1,
                    "p",
                    "R5",
                    "PENDING",
                    "0" * 32,
                    NOW,
                ),
            )

    def test_secret_memory_rejected(self, world: World) -> None:
        with pytest.raises(sqlite3.IntegrityError), transaction(world.conn):
            world.conn.execute(
                "INSERT INTO memories(id, employee_id, type, status, sensitivity, current_version, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), world.employee.id, "FACT", "proposed", "SECRET", 1, NOW, NOW),
            )

    def test_approval_terms_are_immutable(self, world: World) -> None:
        with transaction(world.conn):
            tid = insert_task(world.conn, world.owner_id, world.employee.id)
            aid = insert_action(world.conn, tid)
            apid = insert_approval(world.conn, tid, aid)
        for column, value in [("destination", "other"), ("params_hash", "b" * 64), ("max_uses", 5)]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"), transaction(world.conn):
                world.conn.execute(f"UPDATE approvals SET {column} = ? WHERE id = ?", (value, apid))

    def test_action_input_is_immutable(self, world: World) -> None:
        with transaction(world.conn):
            tid = insert_task(world.conn, world.owner_id, world.employee.id)
            aid = insert_action(world.conn, tid)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"), transaction(world.conn):
            world.conn.execute("UPDATE actions SET input_json = '{}' WHERE id = ?", (aid,))


class TestJournal:
    def test_append_and_resume_by_sequence(self, world: World) -> None:
        actor = Actor("owner", world.owner_id, "local_app")
        with transaction(world.conn):
            e1 = journal.append(
                world.conn,
                world.clock,
                employee_id=world.employee.id,
                type="task.created",
                actor=actor,
                summary="one",
            )
            e2 = journal.append(
                world.conn,
                world.clock,
                employee_id=world.employee.id,
                type="task.updated",
                actor=actor,
                summary="two",
            )
        assert e2["sequence_id"] > e1["sequence_id"]
        after = journal.events_after(world.conn, world.employee.id, e1["sequence_id"])
        assert [e["summary"] for e in after] == ["two"]

    def test_journal_is_append_only(self, world: World) -> None:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"), transaction(world.conn):
            world.conn.execute("UPDATE journal_events SET summary = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"), transaction(world.conn):
            world.conn.execute("DELETE FROM journal_events")

    def test_append_requires_transaction(self, world: World) -> None:
        with pytest.raises(StorageError):
            journal.append(
                world.conn,
                world.clock,
                employee_id=world.employee.id,
                type="task.created",
                actor=Actor("system", "x"),
                summary="x",
            )

    def test_summary_is_redacted(self, world: World) -> None:
        fake = "sk-proj-" + "Z" * 40  # atlas-scan: allow-fake-secret
        with transaction(world.conn):
            ev = journal.append(
                world.conn,
                world.clock,
                employee_id=world.employee.id,
                type="task.note",
                actor=Actor("system", "x"),
                summary=f"leaked {fake} here",
            )
        assert fake not in ev["summary"]
        stored = world.conn.execute(
            "SELECT summary FROM journal_events WHERE event_id=?", (ev["event_id"],)
        ).fetchone()[0]
        assert fake not in stored

    def test_invalid_event_type_rejected(self, world: World) -> None:
        from shared.contracts import ContractError

        with pytest.raises(ContractError), transaction(world.conn):
            journal.append(
                world.conn,
                world.clock,
                employee_id=world.employee.id,
                type="Bad Type",
                actor=Actor("system", "x"),
                summary="x",
            )
