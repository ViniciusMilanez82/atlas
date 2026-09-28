"""Persistent lifecycle for data-only skills. Approval never grants executable-code capabilities."""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from typing import Any

from runtime.skills import table_engine as engine
from shared.actors import Actor
from shared.canonical import canonical_hash
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

LEVELS = ("PUBLIC", "INTERNAL", "PERSONAL", "SENSITIVE", "SECRET")


def strongest(*classes: str) -> str:
    return max(classes, key=lambda c: LEVELS.index(c) if c in LEVELS else len(LEVELS))


class TableLibrary:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn, self.clock = conn, clock

    def owner(self, employee: str, actor: Actor) -> None:
        row = self.conn.execute("SELECT owner_id FROM employees WHERE id=?", (employee,)).fetchone()
        if not row or actor.kind != "owner" or actor.id != row[0] or actor.channel != "local_app":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "Somente o proprietário no aplicativo local pode decidir habilidades.")

    def _row(self, employee: str, version_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self.conn.execute("SELECT * FROM table_skill_versions WHERE id=? AND employee_id=?",
                                (version_id, employee)).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "Versão de habilidade não encontrada neste funcionário.")
        if canonical_hash(json.loads(row["definition_json"])) != row["content_hash"]:
            raise AtlasError(ErrorCode.POLICY_DENIED, "Integridade da habilidade inválida.")
        return row

    def get(self, employee: str, version_id: str, *, detail: bool = True) -> dict[str, Any]:
        row = self._row(employee, version_id)
        result = {k: row[k] for k in ("id", "skill_key", "version", "description", "content_hash",
                                      "classification", "state", "revision", "source_task_id", "failure_count")}
        test = self.conn.execute("SELECT * FROM table_skill_tests WHERE version_id=? ORDER BY rowid DESC LIMIT 1",
                                 (version_id,)).fetchone()
        result["test_id"] = test["id"] if test else None
        result["tests_passed"] = bool(test and test["passed"])
        current_engine = engine.fingerprint()
        result["tests_current"] = bool(test and test["engine_hash"] == current_engine and test["content_hash"] == row["content_hash"])
        result["usable"] = row["state"] == "ACTIVE" and row["approved_engine"] == current_engine
        result["can_activate"] = row["state"] == "TESTED" and result["tests_passed"] and result["tests_current"]
        result["can_rollback"] = row["state"] == "SUPERSEDED" and bool(row["approved_by"]) and row["approved_engine"] == current_engine
        result["permissions"] = ["transformar dados fornecidos", "devolver resultados para a tarefa"]
        if detail:
            result["definition"] = json.loads(row["definition_json"])
            result["test_report"] = json.loads(test["report_json"]) if test else None
            result["uses"] = [dict(r) for r in self.conn.execute(
                "SELECT task_id,output_hash,error_code,created_at FROM table_skill_uses WHERE version_id=? ORDER BY rowid DESC LIMIT 20", (version_id,))]
        return result

    def list(self, employee: str, *, active_only: bool = False) -> list[dict[str, Any]]:
        ids = self.conn.execute("SELECT id FROM table_skill_versions WHERE employee_id=? "
                               + ("AND state='ACTIVE' " if active_only else "")
                               + "ORDER BY rowid DESC LIMIT 200", (employee,)).fetchall()
        result = [self.get(employee, r[0], detail=False) for r in ids]
        return [r for r in result if r["usable"]] if active_only else result

    def _replay(self, employee: str, request_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT request_hash,result_json FROM table_skill_receipts WHERE employee_id=? AND request_id=?",
                                (employee, request_id)).fetchone()
        if not row:
            return None
        if row[0] != canonical_hash(payload):
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "O identificador já pertence a outra decisão.")
        vid = json.loads(row[1])["version_id"]
        return {**self.get(employee, vid), "replayed": True}

    def _receipt(self, employee: str, request_id: str, payload: dict[str, Any], version_id: str) -> None:
        self.conn.execute("INSERT INTO table_skill_receipts VALUES(?,?,?,?,?)", (
            employee, request_id, canonical_hash(payload), json.dumps({"version_id": version_id}), to_utc_str(self.clock.now())))

    def _journal(self, employee: str, actor: Actor, version_id: str, event: str) -> None:
        journal.append(self.conn, self.clock, employee_id=employee, actor=actor, type=f"skill.{event}",
                       summary=f"Declarative table skill {version_id}: {event}")

    def propose(self, employee: str, *, key: str, description: str, definition: dict[str, Any],
                task_id: str, action_id: str, classification: str,
                check_fence: Callable[[], None]) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) or not 1 <= len(description) <= 300:
            raise AtlasError(ErrorCode.INVALID_INPUT, "Nome ou descrição inválidos.")
        if classification not in LEVELS[:-1]:
            raise AtlasError(ErrorCode.POLICY_DENIED, "Habilidades não podem conter segredos.")
        engine.validate_definition(definition)
        payload = {"op": "propose", "key": key, "description": description, "definition": definition,
                   "task_id": task_id, "classification": classification}
        with transaction(self.conn):
            replay = self._replay(employee, action_id, payload)
            if replay is not None:
                return replay
            check_fence()
            # New examples always create a new immutable version, never edit prior evidence.
            count = self.conn.execute("SELECT COUNT(*) FROM table_skill_versions WHERE employee_id=?", (employee,)).fetchone()[0]
            if count >= 200:
                raise AtlasError(ErrorCode.RATE_LIMITED, "Limite de 200 versões atingido nesta edição.")
            version = self.conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM table_skill_versions WHERE employee_id=? AND skill_key=?", (employee, key)).fetchone()[0]
            vid = new_id()
            self.conn.execute("INSERT INTO table_skill_versions(id,employee_id,skill_key,version,description,definition_json,content_hash,classification,source_task_id,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,'DRAFT',?)", (
                vid, employee, key, version, description, json.dumps(definition, ensure_ascii=False),
                canonical_hash(definition), classification, task_id, to_utc_str(self.clock.now())))
            self._receipt(employee, action_id, payload, vid)
            self._journal(employee, Actor("control_plane", "broker", "internal"), vid, "proposed")
        return self.get(employee, vid)

    def test(self, employee: str, version_id: str, expected_revision: int, *, actor: Actor,
             request_id: str, check_fence: Callable[[], None] = lambda: None) -> dict[str, Any]:
        # Only the owner UI exposes this method. Agent adapters use a private trusted actor after
        # broker authorization, and cannot invoke activate/rollback/revoke through this function.
        if actor.kind == "owner":
            self.owner(employee, actor)
        elif actor != Actor("control_plane", "broker", "internal"):
            raise AtlasError(ErrorCode.UNAUTHORIZED, "Teste não autorizado.")
        payload = {"op": "test", "version_id": version_id, "revision": expected_revision}
        replay = self._replay(employee, request_id, payload)
        if replay is not None:
            return replay
        row = self._row(employee, version_id)
        if row["revision"] != expected_revision or row["state"] not in ("DRAFT", "TESTED"):
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "Recarregue a versão antes de testar.")
        report = engine.check_examples(json.loads(row["definition_json"]))
        with transaction(self.conn):
            replay = self._replay(employee, request_id, payload)
            if replay is not None:
                return replay
            check_fence()
            current = self._row(employee, version_id)
            if current["revision"] != expected_revision:
                raise AtlasError(ErrorCode.VERSION_CONFLICT, "A habilidade mudou durante o teste.")
            self.conn.execute("INSERT INTO table_skill_tests VALUES(?,?,?,?,?,?,?)", (
                new_id(), version_id, row["content_hash"], report["engine_hash"], int(report["passed"]),
                json.dumps(report, ensure_ascii=False), to_utc_str(self.clock.now())))
            self.conn.execute("UPDATE table_skill_versions SET state=?,revision=revision+1 WHERE id=?", (
                "TESTED" if report["passed"] else "DRAFT", version_id))
            self._receipt(employee, request_id, payload, version_id)
            self._journal(employee, actor, version_id, "tested")
        return self.get(employee, version_id)

    def decide(self, employee: str, version_id: str, *, actor: Actor, expected_revision: int,
               content_hash: str, test_id: str | None, decision: str, request_id: str) -> dict[str, Any]:
        self.owner(employee, actor)
        payload = {"op": decision, "version_id": version_id, "revision": expected_revision,
                   "content_hash": content_hash, "test_id": test_id}
        with transaction(self.conn):
            replay = self._replay(employee, request_id, payload)
            if replay is not None:
                return replay
            row = self._row(employee, version_id)
            if row["revision"] != expected_revision or row["content_hash"] != content_hash:
                raise AtlasError(ErrorCode.VERSION_CONFLICT, "A versão exibida mudou; confira novamente.")
            info = self.get(employee, version_id)
            if decision in ("activate", "rollback"):
                allowed = info["can_activate"] if decision == "activate" else info["can_rollback"]
                if not allowed or info["test_id"] != test_id or not info["tests_current"] or not info["tests_passed"]:
                    raise AtlasError(ErrorCode.POLICY_DENIED, "Teste atual aprovado e revisão da versão exata são obrigatórios.")
                self.conn.execute("UPDATE table_skill_versions SET state='SUPERSEDED',revision=revision+1 WHERE employee_id=? AND skill_key=? AND state='ACTIVE'", (employee, row["skill_key"]))
                self.conn.execute("UPDATE table_skill_versions SET state='ACTIVE',revision=revision+1,approved_engine=?,approved_by=?,failure_count=0 WHERE id=?",
                                  (engine.fingerprint(), actor.id, version_id))
            elif decision in ("revoke", "quarantine") and row["state"] != "REVOKED":
                self.conn.execute("UPDATE table_skill_versions SET state=?,revision=revision+1 WHERE id=?", (
                    "REVOKED" if decision == "revoke" else "QUARANTINED", version_id))
            else:
                raise AtlasError(ErrorCode.INVALID_INPUT, "Decisão incompatível com o estado da habilidade.")
            self._receipt(employee, request_id, payload, version_id)
            self._journal(employee, actor, version_id, decision)
        return self.get(employee, version_id)

    def active(self, employee: str, version_id: str, content_hash: str) -> sqlite3.Row:
        row = self._row(employee, version_id)
        if row["state"] != "ACTIVE" or row["content_hash"] != content_hash or row["approved_engine"] != engine.fingerprint():
            raise AtlasError(ErrorCode.POLICY_DENIED, "Habilidade não está ativa, compatível e aprovada nesta versão.")
        return row

    def record_failure(self, employee: str, version_id: str, action_id: str, task_id: str, input_hash: str,
                       code: str, check_fence: Callable[[], None]) -> None:
        with transaction(self.conn):
            if self.conn.execute("SELECT 1 FROM table_skill_uses WHERE action_id=?", (action_id,)).fetchone():
                return
            check_fence()
            row = self._row(employee, version_id)
            self.conn.execute("INSERT INTO table_skill_uses VALUES(?,?,?,?,NULL,?,?)", (
                action_id, version_id, task_id, input_hash, code, to_utc_str(self.clock.now())))
            count = int(row["failure_count"]) + 1
            self.conn.execute("UPDATE table_skill_versions SET failure_count=? WHERE id=?", (count, version_id))
            if count >= 3 and row["state"] == "ACTIVE":
                self.conn.execute("UPDATE table_skill_versions SET state='QUARANTINED',revision=revision+1 WHERE id=?", (version_id,))
                self._journal(employee, Actor("control_plane", "broker", "internal"), version_id, "automatic_quarantine")
