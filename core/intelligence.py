"""Intelligence setup for atlas-core (spec 7.2-7.4, UX-004).

The model is usable only when ALL of these hold, and the reason for any gap is reported verbatim to
the app: a credential exists in the Vault (Keychain on macOS), settings with budget ceilings were
saved, the configured provider is supported, and the exact model id passed an owner-authorized
"Testar inteligência". Nothing here falls back to another provider or to a guessed model.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from runtime.models.intelligence_check import run_intelligence_check
from runtime.models.openai_responses import DEFAULT_BASE_URL, OpenAIResponsesProvider
from runtime.models.pricing import SPEC_REFERENCE_TABLE
from runtime.models.router import BudgetedModelClient, CatalogEntry, Consent, ModelRouter
from runtime.models.types import ModelCapabilities
from security.budget.budget import BudgetLimits, BudgetManager
from security.vault.vault import SecretValue, Vault, VaultError
from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

PURPOSE = "model_inference"
BROKER = Actor("control_plane", "model-client", "internal")
CAPS = ModelCapabilities(structured_output=True)


@dataclass(frozen=True)
class IntelligenceStatus:
    configured: bool
    reason: str
    model_id: str | None = None


class IntelligenceSetup:
    def __init__(
        self, conn: sqlite3.Connection, clock: Clock, vault: Vault | None, base_url: str = DEFAULT_BASE_URL
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.vault = vault
        self.base_url = base_url.rstrip("/")

    @property
    def destination(self) -> str:
        return self.base_url + "/responses"

    def latest_config(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT config_json FROM settings ORDER BY revision DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def _model(self, cfg: dict[str, Any]) -> tuple[str, str]:
        profile = cfg["intelligence"]["profiles"][cfg["intelligence"]["default_profile"]]
        return str(profile["provider"]), str(profile["model_id"])

    def _credential_ref(self) -> str:
        if self.vault is None:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "credential store (Keychain service) is not available")
        try:
            return self.vault.find_ref(purpose=PURPOSE, destination=self.destination)
        except VaultError as exc:
            raise AtlasError(ErrorCode.UNAUTHORIZED, str(exc)) from None

    def key_provider(self) -> SecretValue:
        ref = self._credential_ref()
        assert self.vault is not None
        with self.vault.use(
            ref,
            actor=Actor("control_plane", "broker", "internal"),
            purpose=PURPOSE,
            destination=self.destination,
        ) as secret:
            return SecretValue(secret.reveal())

    def status(self) -> IntelligenceStatus:
        if self.vault is None:
            return IntelligenceStatus(False, "credential store (Keychain service) is not available")
        try:
            self._credential_ref()
        except AtlasError:
            return IntelligenceStatus(False, "no API credential registered")
        cfg = self.latest_config()
        if cfg is None:
            return IntelligenceStatus(False, "settings with budget ceilings were not saved yet")
        b = cfg["budget"]
        if b["monthly_limit_minor"] is None or b["per_task_limit_minor"] is None:
            return IntelligenceStatus(False, "budget ceilings are not set (paid calls stay blocked)")
        provider, model = self._model(cfg)
        if provider != "openai":
            return IntelligenceStatus(False, f"provider {provider} has no adapter yet", model)
        row = self.conn.execute(
            "SELECT passed FROM intelligence_validations WHERE provider = ? AND model_id = ?"
            " ORDER BY checked_at DESC LIMIT 1",
            (provider, model),
        ).fetchone()
        if not row or not row[0]:
            return IntelligenceStatus(
                False, f"model {model} was not validated by 'Testar inteligência'", model
            )
        return IntelligenceStatus(True, "ready", model)

    def build_client(self) -> BudgetedModelClient:
        st = self.status()
        if not st.configured or st.model_id is None:
            raise AtlasError(ErrorCode.MODEL_UNSUPPORTED, st.reason)
        cfg = self.latest_config()
        assert cfg is not None
        provider = OpenAIResponsesProvider(
            self.key_provider, capabilities={st.model_id: CAPS}, base_url=self.base_url
        )
        router = ModelRouter(
            [CatalogEntry("openai", st.model_id, "general", 2, CAPS, validated=True)],
            Consent({"openai"}),
            mode="manual",
            manual_model=st.model_id,
        )
        return BudgetedModelClient(
            self.conn,
            self.clock,
            router,
            {"openai": provider},
            SPEC_REFERENCE_TABLE,
            BudgetManager(self.conn, self.clock, BudgetLimits.from_config(cfg)),
        )

    # ---------------------------------------------------------------- owner operations

    def register_key(self, *, actor: Actor, employee_id: str, secret: bytes) -> str:
        if self.vault is None:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "credential store (Keychain service) is not available")
        try:
            ref = self.vault.register(
                actor=actor,
                employee_id=employee_id,
                provider="openai",
                scope="api",
                purpose=PURPOSE,
                allowed_destinations=[self.base_url + "/*"],
                secret=secret,
            )
        except VaultError as exc:
            raise AtlasError(ErrorCode.UNAUTHORIZED, str(exc)) from None
        return ref.id

    def run_check(
        self, *, actor: Actor, employee_id: str, model_id: str, max_cost_minor: int
    ) -> dict[str, Any]:
        if actor.kind != "owner" or actor.channel != "local_app":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner on the local app runs a billable check")
        self._credential_ref()
        report = run_intelligence_check(
            key_provider=self.key_provider,
            model_id=model_id,
            max_cost_minor=max_cost_minor,
            base_url=self.base_url,
        )
        data: dict[str, Any] = json.loads(report.to_json())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO intelligence_validations(id, provider, model_id, passed, report_json, cost_minor, currency,"
                " checked_at, checked_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    "openai",
                    model_id,
                    int(report.passed),
                    report.to_json(),
                    report.cost_minor,
                    report.currency,
                    to_utc_str(self.clock.now()),
                    f"{actor.kind}:{actor.id}",
                ),
            )
            journal.append(
                self.conn,
                self.clock,
                employee_id=employee_id,
                type="intelligence.checked",
                actor=actor,
                summary=f"model {model_id}: {'passed' if report.passed else 'failed'}; "
                f"cost {report.cost_minor} {report.currency or ''}".strip(),
            )
        return data
