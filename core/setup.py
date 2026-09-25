"""N22: first-use setup and editable identity on the authenticated local owner channel.

No credential or paid call is created here. Completion acknowledges a LOCAL setup, not
homologation of the product; the owner may deliberately choose limited mode without inference.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.intelligence import IntelligenceSetup
from core.ipc.sessions import Session
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from storage import journal
from storage.db import transaction

LOCALES = ("pt-BR", "en-US", "es-ES")


class SetupService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, intelligence: IntelligenceSetup | None) -> None:
        self.conn = conn
        self.clock = clock
        self.intelligence = intelligence

    def identity(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT e.id, e.name, e.locale, e.timezone, o.display_name, e.profile_version, e.owner_id "
            "FROM employees e JOIN owners o ON o.id = e.owner_id WHERE e.id = ?",
            (session.employee_id,),
        ).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "employee is not available in this session")
        return {
            "employee_id": row[0], "name": row[1], "locale": row[2], "timezone": row[3],
            "owner_name": row[4], "profile_version": row[5], "actor_kind": session.actor.kind,
            "settings_revision": int(self.conn.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM settings"
            ).fetchone()[0]),
        }

    def _owner(self, session: Session) -> None:
        actor = session.actor
        row = self.conn.execute("SELECT owner_id FROM employees WHERE id = ?", (session.employee_id,)).fetchone()
        if (row is None or actor.kind != "owner" or actor.id != row[0] or actor.channel != "local_app"):
            raise AtlasError(ErrorCode.UNAUTHORIZED, "setup changes require this employee's owner in the local app")

    @staticmethod
    def _name(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 100 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise AtlasError(ErrorCode.INVALID_INPUT, "name must contain 1 to 100 printable characters")
        return value

    def update_identity(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        self._owner(session)
        name = self._name(params["name"])
        owner = self._name(params["owner_name"])
        locale, timezone = params["locale"], params["timezone"]
        if locale not in LOCALES:
            raise AtlasError(ErrorCode.INVALID_INPUT, "locale is not supported")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise AtlasError(ErrorCode.INVALID_INPUT, "invalid IANA timezone") from None
        with transaction(self.conn):
            current = self.identity(session, {})
            if current["profile_version"] != params["expected_profile_version"]:
                raise AtlasError(ErrorCode.VERSION_CONFLICT, "profile changed; reload before saving")
            self.conn.execute(
                "UPDATE employees SET name = ?, locale = ?, timezone = ?, profile_version = profile_version + 1 "
                "WHERE id = ? AND profile_version = ?",
                (name, locale, timezone, session.employee_id, params["expected_profile_version"]),
            )
            self.conn.execute("UPDATE owners SET display_name = ? WHERE id = ?", (owner, session.actor.id))
            journal.append(self.conn, self.clock, employee_id=session.employee_id,
                           type="identity.updated", actor=session.actor,
                           summary=f"local owner updated profile revision {current['profile_version'] + 1}")
        return self.identity(session, {})

    def status(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        identity = self.identity(session, {})
        intel = self.intelligence.status() if self.intelligence else None
        ready = bool(intel and intel.configured)
        finished = self.conn.execute(
            "SELECT completed_at FROM employee_setup WHERE employee_id = ?", (session.employee_id,)
        ).fetchone()
        named = identity["profile_version"] > 1
        configured = identity["settings_revision"] > 0
        return {
            "identity": identity, "completed": finished is not None,
            "completed_at": finished[0] if finished else None,
            "identity_saved": named, "settings_saved": configured,
            "intelligence_ready": ready,
            "intelligence_reason": intel.reason if intel else "intelligence setup not loaded",
            "can_finish": named and configured and ready,
            "can_finish_limited": named and configured,
            "mode": "ready" if ready else "limited",
            "product_stage": "alpha",
        }

    def complete(self, session: Session, params: dict[str, Any]) -> dict[str, Any]:
        self._owner(session)
        with transaction(self.conn):
            state = self.status(session, {})
            identity = state["identity"]
            if (identity["profile_version"] != params["expected_profile_version"] or
                    identity["settings_revision"] != params["expected_settings_revision"]):
                raise AtlasError(ErrorCode.VERSION_CONFLICT, "setup changed; reload the current state")
            if not state["can_finish_limited"]:
                raise AtlasError(ErrorCode.INVALID_INPUT, "save identity and settings first")
            if not state["intelligence_ready"] and not params["allow_limited_mode"]:
                raise AtlasError(ErrorCode.MODEL_UNSUPPORTED, "validate intelligence or explicitly choose limited mode")
            if not state["completed"]:
                self.conn.execute(
                    "INSERT INTO employee_setup(employee_id, completed_at, profile_version, settings_revision, mode) "
                    "VALUES (?,?,?,?,?)",
                    (session.employee_id, to_utc_str(self.clock.now()), identity["profile_version"],
                     identity["settings_revision"], state["mode"]),
                )
                journal.append(self.conn, self.clock, employee_id=session.employee_id,
                               type="setup.completed", actor=session.actor,
                               summary=f"owner acknowledged local setup in {state['mode']} mode; product remains alpha")
        return self.status(session, {})
