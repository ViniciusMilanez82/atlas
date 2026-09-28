"""Owner-only review endpoints. Runtime tool proposals never acquire these decision rights."""
from __future__ import annotations

import sqlite3
from typing import Any

from core.ipc.sessions import Session
from runtime.skills.table_library import TableLibrary
from shared.clock import Clock


class TableSkillsService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.library = TableLibrary(conn, clock)
        self.handlers = {"skills.list": self.list, "skills.get": self.get,
                         "skills.test": self.test, "skills.decide": self.decide}

    def list(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        self.library.owner(session.employee_id, session.actor)
        return {"skills": self.library.list(session.employee_id)}

    def get(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        self.library.owner(session.employee_id, session.actor)
        return self.library.get(session.employee_id, params["version_id"])

    def test(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        self.library.owner(session.employee_id, session.actor)
        return self.library.test(session.employee_id, params["version_id"], params["expected_revision"],
                                 actor=session.actor, request_id=params["request_id"])

    def decide(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        return self.library.decide(session.employee_id, params["version_id"], actor=session.actor,
            expected_revision=params["expected_revision"], content_hash=params["content_hash"],
            test_id=params["test_id"], decision=params["decision"], request_id=params["request_id"])
