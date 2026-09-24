"""Intelligence setup for atlas-core (spec 7.2-7.4, UX-004; review A8).

The model is usable only when ALL of these hold, and the reason for any gap is reported verbatim:
a credential exists in the Vault (Keychain on macOS); settings with budget ceilings were saved;
the provider is supported; prices are either verified OR the owner explicitly accepted the reference
table as an ESTIMATE (never shown as a homologated ceiling); and the exact model id passed an
owner-authorized "Testar inteligência". Model access and price validity are separate facts.

'Testar inteligência' is billed through the SAME global budget ledger as every other call (monthly
ceiling included), one check at a time.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from runtime.models.intelligence_check import SCHEMA as CHECK_SCHEMA
from runtime.models.intelligence_check import IntelligenceReport
from runtime.models.openai_responses import DEFAULT_BASE_URL, OpenAIResponsesProvider
from runtime.models.pricing import SPEC_REFERENCE_TABLE, PriceTable
from runtime.models.router import BudgetedModelClient, CatalogEntry, Consent, ModelRouter, Requirements
from runtime.models.types import Message, ModelCapabilities, ModelRequest, ProviderCallError, Role
from security.budget.budget import BudgetError, BudgetManager
from security.egress.guard import EgressGuard
from security.vault.vault import SecretValue, Vault, VaultError
from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

PURPOSE = "model_inference"
CAPS = ModelCapabilities(structured_output=True)
# Part of the validation binding (A3-29): changing what Atlas relies on requires a new check.
CAPABILITY_VERSION = "caps-" + hashlib.sha256(repr(CAPS).encode()).hexdigest()[:12]
# Provisional quality order of the profiles until Atlas evaluations with real models exist (N13, D-03):
# it only orders VALIDATED candidates; it never makes an unvalidated model usable.
PROFILE_RANK = {"light": 1, "general": 2, "deep": 3}
_CHECK_LOCK = threading.Lock()


@dataclass(frozen=True)
class IntelligenceStatus:
    configured: bool
    reason: str
    model_id: str | None = None
    price_table: str = SPEC_REFERENCE_TABLE.version
    prices_verified: bool = SPEC_REFERENCE_TABLE.verified


class IntelligenceSetup:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        vault: Vault | None,
        base_url: str = DEFAULT_BASE_URL,
        prices: PriceTable = SPEC_REFERENCE_TABLE,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.vault = vault
        self.base_url = base_url.rstrip("/")
        self.prices = prices

    @property
    def destination(self) -> str:
        return self.base_url + "/responses"

    # ---------------------------------------------------------------- settings

    def settings(self) -> tuple[int, dict[str, Any] | None]:
        row = self.conn.execute(
            "SELECT revision, config_json FROM settings ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        return (int(row[0]), json.loads(row[1])) if row else (0, None)

    def latest_config(self) -> dict[str, Any] | None:
        return self.settings()[1]

    @staticmethod
    def _model(cfg: dict[str, Any]) -> tuple[str, str]:
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

    def _price_gate(self, cfg: dict[str, Any], model: str) -> str | None:
        try:
            self.prices.get("openai", model)
        except KeyError:
            return f"model {model} has no entry in price table {self.prices.version}; paid calls stay blocked"
        if not self.prices.verified and not cfg["budget"].get("accept_reference_prices", False):
            return (
                f"price table {self.prices.version} is not verified; accept it explicitly as an estimate in "
                "Configurações before any paid call"
            )
        return None

    def _preconditions(self) -> tuple[dict[str, Any], str] | str:
        """Everything except the model validation. Returns (cfg, model) or the blocking reason."""
        if self.vault is None:
            return "credential store (Keychain service) is not available"
        try:
            self._credential_ref()
        except AtlasError:
            return "no API credential registered"
        cfg = self.latest_config()
        if cfg is None:
            return "settings with budget ceilings were not saved yet"
        b = cfg["budget"]
        if b["monthly_limit_minor"] is None or b["per_task_limit_minor"] is None:
            return "budget ceilings are not set (paid calls stay blocked)"
        provider, model = self._model(cfg)
        if provider != "openai":
            return f"provider {provider} has no adapter yet"
        gate = self._price_gate(cfg, model)
        if gate:
            return gate
        return cfg, model

    def validated_models(self) -> set[str]:
        """Models whose LATEST check for the current credential/endpoint/capabilities passed (A3-29)."""
        try:
            ref = self._credential_ref()
        except AtlasError:
            return set()
        ok: set[str] = set()
        rows = self.conn.execute(
            "SELECT model_id, passed FROM intelligence_validations WHERE provider = 'openai' AND credential_ref = ?"
            " AND endpoint = ? AND capability_version = ? ORDER BY checked_at, rowid",
            (ref, self.destination, CAPABILITY_VERSION),
        ).fetchall()
        for model_id, passed in rows:  # the latest result per model wins
            if passed:
                ok.add(model_id)
            else:
                ok.discard(model_id)
        return ok

    def profiles(self, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        """Every configured profile with what is known about it: validated? priced? (UI: 'o que falta validar')."""
        ok = self.validated_models()
        out = []
        for name, prof in cfg["intelligence"]["profiles"].items():
            try:
                self.prices.get(prof["provider"], prof["model_id"])
                priced = True
            except KeyError:
                priced = False
            out.append({
                "profile": name,
                "provider": prof["provider"],
                "model_id": prof["model_id"],
                "validated": prof["model_id"] in ok,
                "priced": priced,
                "rank": PROFILE_RANK.get(name, 2),
            })
        return out

    def status(self) -> IntelligenceStatus:
        pre = self._preconditions()
        if isinstance(pre, str):
            cfg = self.latest_config()
            model = self._model(cfg)[1] if cfg else None
            return IntelligenceStatus(False, pre, model, self.prices.version, self.prices.verified)
        _, model = pre
        row = self.conn.execute(
            "SELECT passed FROM intelligence_validations WHERE provider = 'openai' AND model_id = ?"
            " AND credential_ref = ? AND endpoint = ? AND capability_version = ?"
            " ORDER BY checked_at DESC, rowid DESC LIMIT 1",
            (model, self._credential_ref(), self.destination, CAPABILITY_VERSION),
        ).fetchone()
        if not row or not row[0]:
            return IntelligenceStatus(
                False,
                f"model {model} was not validated for the current credential and endpoint by "
                "'Testar inteligência'",
                model,
                self.prices.version,
                self.prices.verified,
            )
        return IntelligenceStatus(True, "ready", model, self.prices.version, self.prices.verified)

    def _client(
        self, cfg: dict[str, Any], model: str, per_call_cap: int | None = None, *, only_model: bool = False
    ) -> BudgetedModelClient:
        """N13: the router gets every VALIDATED and priced profile, and the mode chosen by the owner
        really changes the selection (automatic by complexity, economic cheapest, max_quality strongest,
        manual = the default profile). ``only_model`` pins one model (used by the check itself)."""
        if only_model:
            entries = [CatalogEntry("openai", model, "check", 2, CAPS, validated=True)]
            mode, manual = "manual", model
        else:
            entries = [
                CatalogEntry("openai", p["model_id"], p["profile"], p["rank"], CAPS, validated=True)
                for p in self.profiles(cfg)
                if p["validated"] and p["priced"] and p["provider"] == "openai"
            ]
            mode = str(cfg["intelligence"].get("mode", "automatic"))
            manual = model
            if mode == "manual":
                entries = [e for e in entries if e.model_id == model]
        provider = OpenAIResponsesProvider(
            self.key_provider, capabilities={e.model_id: CAPS for e in entries}, base_url=self.base_url
        )
        router = ModelRouter(
            entries,
            # Sensitive disclosure is decided per purpose by the Egress Guard on the final payload.
            Consent({"openai"}, sensitive_data_providers={"openai"}),
            mode=mode,
            manual_model=manual,
        )
        # ceilings are read live inside each reservation, never from this snapshot (A3-19)
        return BudgetedModelClient(
            self.conn,
            self.clock,
            router,
            {"openai": provider},
            self.prices,
            BudgetManager.live(self.conn, self.clock, cap_minor=per_call_cap),
            egress=EgressGuard(self.conn),
        )

    def build_client(self) -> BudgetedModelClient:
        st = self.status()
        if not st.configured or st.model_id is None:
            raise AtlasError(ErrorCode.MODEL_UNSUPPORTED, st.reason)
        cfg = self.latest_config()
        assert cfg is not None
        return self._client(cfg, st.model_id)

    # ---------------------------------------------------------------- owner operations

    def register_key(self, *, actor: Actor, employee_id: str, secret: bytes) -> str:
        if self.vault is None:
            raise AtlasError(ErrorCode.UNAUTHORIZED, "credential store (Keychain service) is not available")
        try:
            # A new key REPLACES the previous one for this endpoint (A3-29): the old reference is revoked
            # first, so a validation made with the old key can never vouch for the new one.
            for row in self.conn.execute(
                "SELECT id FROM credential_refs WHERE purpose = ? AND revoked_at IS NULL", (PURPOSE,)
            ).fetchall():
                ref_old = self.vault.get_ref(row[0])
                if any(fnmatch.fnmatchcase(self.destination, pat) for pat in ref_old.allowed_destinations):
                    self.vault.revoke(ref_old.id, actor, employee_id)
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
        if not _CHECK_LOCK.acquire(blocking=False):
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "a check is already running; wait for its result")
        try:
            return self._run_check(actor, employee_id, model_id, max_cost_minor)
        finally:
            _CHECK_LOCK.release()

    def _run_check(
        self, actor: Actor, employee_id: str, model_id: str, max_cost_minor: int
    ) -> dict[str, Any]:
        pre = self._preconditions()
        if isinstance(pre, str):
            raise AtlasError(ErrorCode.MODEL_UNSUPPORTED, pre)
        cfg, _default_model = pre
        configured = {p["model_id"] for p in cfg["intelligence"]["profiles"].values()}
        if model_id not in configured:
            raise AtlasError(
                ErrorCode.INVALID_INPUT, f"save settings with model {model_id} in a profile before testing it"
            )
        try:
            self.prices.get("openai", model_id)
        except KeyError:
            raise AtlasError(
                ErrorCode.MODEL_UNSUPPORTED, f"model {model_id} has no price entry; paid calls stay blocked"
            ) from None
        report = IntelligenceReport(
            "openai", model_id, self.prices.version, self.prices.verified, to_utc_str(self.clock.now())
        )
        provider = OpenAIResponsesProvider(
            self.key_provider, capabilities={model_id: CAPS}, base_url=self.base_url
        )
        try:
            report.model_listed = provider.check_model_access(model_id)
        except (AtlasError, ProviderCallError) as exc:
            report.errors.append(f"model check failed: {type(exc).__name__}")
        if report.model_listed:
            client = self._client(cfg, model_id, per_call_cap=max_cost_minor, only_model=True)
            request = ModelRequest(
                model_id,
                (Message(Role.USER, 'Reply with JSON: {"ok": true, "word": "atlas"}.'),),
                max_output_tokens=64,
                json_schema=CHECK_SCHEMA,
                timeout_s=60,
            )
            try:
                resp = client.call(
                    task_id=None,
                    employee_id=employee_id,
                    purpose="intelligence_check",
                    req=Requirements(structured_output=True, data_classification="PUBLIC"),
                    request=request,
                )
                report.call_succeeded = True
                report.request_id = resp.request_id
                if resp.usage:
                    report.usage = {
                        "input_tokens": resp.usage.input_tokens,
                        "cached_input_tokens": resp.usage.cached_input_tokens,
                        "output_tokens": resp.usage.output_tokens,
                    }
                if resp.estimated_cost:
                    report.cost_minor = resp.estimated_cost.amount_minor
                    report.currency = resp.estimated_cost.currency
                try:
                    parsed: Any = json.loads(resp.output_text)
                    report.output_valid = parsed.get("ok") is True and isinstance(parsed.get("word"), str)
                except (json.JSONDecodeError, AttributeError):
                    report.errors.append("output was not the requested JSON")
            except BudgetError as exc:
                report.errors.append(f"budget: {exc.reason}")
            except AtlasError as exc:
                report.errors.append(f"call failed: {exc.code}: {exc.message}")
        elif report.model_listed is False:
            report.errors.append("the account does not list this model id")
        data: dict[str, Any] = json.loads(report.to_json())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO intelligence_validations(id, provider, model_id, passed, report_json, cost_minor, currency,"
                " checked_at, checked_by, credential_ref, endpoint, capability_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    self._credential_ref(),
                    self.destination,
                    CAPABILITY_VERSION,
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
