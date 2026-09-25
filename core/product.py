"""Owner-facing setup and privacy operations (N22).

Only the authenticated local owner changes these settings. Mutations use an immutable
receipt plus optimistic revision in the SAME transaction as the effect. A reconnect
never accepts a changed payload, resets another settings section, or guesses consent.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.ipc.sessions import Session
from shared.clock import Clock, to_utc_str
from shared.config import load_config, parse_config
from shared.errors import AtlasError, ErrorCode
from storage import journal
from storage.db import transaction

METHODS = ("setup.get", "setup.update", "privacy.get", "privacy.update")


class ProductService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def _owner(self, session: Session) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT e.*, o.display_name FROM employees e JOIN owners o ON o.id=e.owner_id WHERE e.id=?",
            (session.employee_id,),
        ).fetchone()
        if (row is None or session.actor.kind != "owner" or session.actor.id != row["owner_id"]
                or session.actor.channel != "local_app"):
            raise AtlasError(ErrorCode.UNAUTHORIZED, "esta operação exige o proprietário no aplicativo local")
        return row

    def handle(self, session: Session, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._owner(session)
        if method == "setup.get":
            return self.profile(session)
        if method == "privacy.get":
            return self.privacy()
        # Include method and EVERY field, including expected revision, in the receipt.
        digest = hashlib.sha256(json.dumps(
            {"method": method, "params": {k: v for k, v in params.items() if k not in ("correlation_id", "schema_version")}}, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT payload_hash, result_json FROM product_receipts WHERE employee_id=? AND request_id=?",
                (session.employee_id, params["request_id"]),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise AtlasError(ErrorCode.VERSION_CONFLICT, "o mesmo pedido foi reenviado com dados diferentes")
                result: dict[str, Any] = json.loads(row[1])
                return result
            if method == "setup.update":
                result = self._profile_update(session, params)
            elif method == "privacy.update":
                result = self._privacy_update(session, params)
            else:
                raise AtlasError(ErrorCode.INVALID_INPUT, "operação de configuração desconhecida")
            self.conn.execute(
                "INSERT INTO product_receipts(employee_id,request_id,payload_hash,result_json,created_at)"
                " VALUES (?,?,?,?,?)",
                (session.employee_id, params["request_id"], digest, json.dumps(result), to_utc_str(self.clock.now())),
            )
        return result

    def profile(self, session: Session) -> dict[str, Any]:
        row = self._owner(session)
        progress = self.conn.execute(
            "SELECT step FROM onboarding_progress WHERE employee_id=?", (session.employee_id,),
        ).fetchone()
        return {
            "name": row["name"], "owner_name": row["display_name"], "locale": row["locale"],
            "timezone": row["timezone"], "revision": row["profile_version"],
            "step": progress[0] if progress else "welcome",
            # Setup progress is NOT a product certification or a claim of API availability.
            "workspace_available": False, "remote_available": False,
            "storage_encrypted": False,
        }

    @staticmethod
    def _name(value: str) -> str:
        value = unicodedata.normalize("NFC", value).strip()
        if not value or any(unicodedata.category(c).startswith("C") for c in value):
            raise AtlasError(ErrorCode.INVALID_INPUT, "o nome deve conter texto sem caracteres de controle")
        return value

    def _profile_update(self, session: Session, p: dict[str, Any]) -> dict[str, Any]:
        row = self._owner(session)
        if row["profile_version"] != p["expected_revision"]:
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "o perfil mudou; recarregue antes de salvar")
        try:
            ZoneInfo(p["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise AtlasError(ErrorCode.INVALID_INPUT, "fuso horário IANA desconhecido") from None
        name, owner_name = self._name(p["name"]), self._name(p["owner_name"])
        self.conn.execute(
            "UPDATE employees SET name=?, locale=?, timezone=?, profile_version=profile_version+1 WHERE id=?",
            (name, p["locale"], p["timezone"], session.employee_id),
        )
        self.conn.execute("UPDATE owners SET display_name=? WHERE id=?", (owner_name, row["owner_id"]))
        self.conn.execute(
            "INSERT INTO onboarding_progress(employee_id,step,updated_at) VALUES (?,?,?)"
            " ON CONFLICT(employee_id) DO UPDATE SET step=excluded.step,updated_at=excluded.updated_at",
            (session.employee_id, p["step"], to_utc_str(self.clock.now())),
        )
        journal.append(self.conn, self.clock, employee_id=session.employee_id, type="profile.updated",
                       actor=session.actor, summary=f"profile revision {row['profile_version'] + 1}")
        return self.profile(session)

    def _settings(self) -> tuple[int, dict[str, Any]]:
        row = self.conn.execute("SELECT revision,config_json FROM settings ORDER BY revision DESC LIMIT 1").fetchone()
        if row:
            return int(row[0]), json.loads(row[1])
        # Bundled defaults have null budget: privacy setup cannot accidentally enable paid calls.
        return 0, load_config(Path(__file__).resolve().parents[1] / "config/atlas.default.yaml")

    def privacy(self) -> dict[str, Any]:
        rev, cfg = self._settings()
        return {"revision": rev, "privacy": cfg.get("privacy", {"sensitive_consents": []}),
                "research": cfg.get("research", {"web_enabled": False, "allowed_domains": [], "blocked_domains": []})}

    def _privacy_update(self, session: Session, p: dict[str, Any]) -> dict[str, Any]:
        rev, cfg = self._settings()
        if rev != p["expected_revision"]:
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "as configurações mudaram; revise e tente novamente")
        # Only these two sections can change through this method; billing/security remain untouched.
        cfg["privacy"] = p["privacy"]
        cfg["research"] = p["research"]
        parse_config(cfg)
        self.conn.execute(
            "INSERT INTO settings(revision,config_json,updated_at,updated_by) VALUES (?,?,?,?)",
            (rev + 1, json.dumps(cfg, sort_keys=True), to_utc_str(self.clock.now()), f"owner:{session.actor.id}"),
        )
        journal.append(self.conn, self.clock, employee_id=session.employee_id, type="privacy.updated",
                       actor=session.actor, summary=f"explicit local privacy/research configuration, revision {rev + 1}")
        return self.privacy()
