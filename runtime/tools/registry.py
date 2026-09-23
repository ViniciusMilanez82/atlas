"""Trusted Tool Registry (spec 10.1, AT-007.1).

Effect class and base risk are declared by the trusted adapter manifest and validated here -
never chosen by the LLM. New registrations start disabled until validated. There is no host shell
and no secret-reading tool: such capabilities are refused at registration.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from shared.actors import Actor
from shared.canonical import canonical_hash
from shared.clock import Clock, to_utc_str
from storage.db import transaction

EFFECT_MIN_RISK = {"READ_ONLY": "R0", "LOCAL_WRITE": "R1", "EXTERNAL_WRITE": "R2", "IRREVERSIBLE": "R4"}
RISK_ORDER = ["R0", "R1", "R2", "R3", "R4", "R5"]

# Capabilities that make a tool an external writer no matter what it claims.
EXTERNAL_WRITE_CAPABILITIES = frozenset(
    {
        "messaging.send",
        "email.send",
        "file.share",
        "account.create",
        "calendar.write",
        "commerce.purchase",
        "commerce.subscribe",
        "commerce.cancel_booking",
        "storage.delete_permanent",
    }
)
IRREVERSIBLE_CAPABILITIES = frozenset(
    {"commerce.purchase", "commerce.subscribe", "commerce.cancel_booking", "storage.delete_permanent"}
)
# Never registrable (spec 5.4, 10.1, 11.4, 11.1 R5).
FORBIDDEN_CAPABILITIES = frozenset(
    {
        "host.shell",
        "host.filesystem",
        "secret.read",
        "secret.export",
        "policy.write",
        "broker.modify",
        "browser.personal_profile",
        "security.disable",
    }
)
NETWORK_POLICIES = frozenset({"none", "owner_channel", "allowlist", "public"})
_TOOL_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class RegistryError(ValueError):
    pass


def risk_max(a: str, b: str) -> str:
    return a if RISK_ORDER.index(a) >= RISK_ORDER.index(b) else b


@dataclass(frozen=True)
class ToolManifest:
    tool_id: str
    version: str
    description: str
    input_schema: dict[str, Any]
    effect_class: str
    base_risk: str
    capabilities: tuple[str, ...] = ()
    network_policy: str = "none"
    destination_field: str | None = None
    cost_field: str | None = None
    cost_category: str | None = None  # inference | paid_tool | purchase
    timeout_s: int = 30
    supports_idempotency_key: bool = False
    credential_purpose: str | None = None
    verification: str = "deterministic_check"
    purchase_fields: tuple[str, ...] = field(default=())
    isolation: str = "thread"  # thread: trusted cooperative adapter; process: killable child process

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["capabilities"] = list(self.capabilities)
        d["purchase_fields"] = list(self.purchase_fields)
        return d

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self.to_json())

    def validate(self) -> None:
        if not _TOOL_ID.match(self.tool_id):
            raise RegistryError("tool_id must be a lowercase dotted identifier")
        if not _SEMVER.match(self.version):
            raise RegistryError("version must be semver MAJOR.MINOR.PATCH")
        if self.effect_class not in EFFECT_MIN_RISK:
            raise RegistryError(f"unknown effect class {self.effect_class}")
        if self.base_risk not in RISK_ORDER:
            raise RegistryError(f"unknown risk {self.base_risk}")
        caps = set(self.capabilities)
        if bad := caps & FORBIDDEN_CAPABILITIES:
            raise RegistryError(f"forbidden capability: {sorted(bad)}")
        if self.base_risk == "R5":
            raise RegistryError("R5 actions are always denied and cannot be registered as tools")
        if RISK_ORDER.index(self.base_risk) < RISK_ORDER.index(EFFECT_MIN_RISK[self.effect_class]):
            raise RegistryError(f"{self.effect_class} requires at least {EFFECT_MIN_RISK[self.effect_class]}")
        if caps & EXTERNAL_WRITE_CAPABILITIES and self.effect_class in ("READ_ONLY", "LOCAL_WRITE"):
            raise RegistryError("a tool with external-write capabilities cannot declare itself read/local")
        if caps & IRREVERSIBLE_CAPABILITIES and (
            self.effect_class != "IRREVERSIBLE" or self.base_risk != "R4"
        ):
            raise RegistryError(
                "purchases, subscriptions, cancellations and permanent deletes are IRREVERSIBLE/R4"
            )
        if self.effect_class in ("EXTERNAL_WRITE", "IRREVERSIBLE") and not self.destination_field:
            raise RegistryError("external effects must declare which input field is the destination")
        if self.network_policy not in NETWORK_POLICIES:
            raise RegistryError(f"unknown network policy {self.network_policy}")
        if (self.cost_field is None) != (self.cost_category is None):
            raise RegistryError("cost_field and cost_category go together")
        if "commerce.purchase" in caps and (self.cost_category != "purchase" or not self.purchase_fields):
            raise RegistryError("purchase tools must declare cost and purchase detail fields")
        if self.isolation not in ("thread", "process"):
            raise RegistryError("isolation must be 'thread' or 'process'")
        if self.isolation == "process" and self.credential_purpose is not None:
            raise RegistryError("process-isolated tools never receive credentials")
        if not 0 < self.timeout_s <= 600:
            raise RegistryError("timeout_s must be between 1 and 600 seconds")
        Draft202012Validator.check_schema(self.input_schema)
        if (
            self.input_schema.get("type") != "object"
            or self.input_schema.get("additionalProperties") is not False
        ):
            raise RegistryError("tool input schema must be a closed object")


class ToolAdapter(Protocol):
    def __call__(self, tool_input: dict[str, Any], context: Any) -> Any: ...


class ToolRegistry:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock
        self._adapters: dict[tuple[str, str], tuple[str, ToolAdapter]] = {}

    def register(self, manifest: ToolManifest, adapter: ToolAdapter) -> None:
        """Register a trusted adapter. It starts DISABLED until validated and enabled."""
        manifest.validate()
        with transaction(self.conn):
            existing = self.conn.execute(
                "SELECT manifest_hash FROM tools WHERE tool_id = ? AND version = ?",
                (manifest.tool_id, manifest.version),
            ).fetchone()
            if existing and existing["manifest_hash"] != manifest.manifest_hash:
                raise RegistryError("a different manifest is already registered for this tool version")
            if not existing:
                self.conn.execute(
                    "INSERT INTO tools(tool_id, version, effect_class, base_risk, manifest_json, manifest_hash,"
                    " enabled, registered_at) VALUES (?,?,?,?,?,?,0,?)",
                    (
                        manifest.tool_id,
                        manifest.version,
                        manifest.effect_class,
                        manifest.base_risk,
                        json.dumps(manifest.to_json(), sort_keys=True),
                        manifest.manifest_hash,
                        to_utc_str(self.clock.now()),
                    ),
                )
        self._adapters[(manifest.tool_id, manifest.version)] = (manifest.manifest_hash, adapter)

    def enable(self, tool_id: str, version: str, *, actor: Actor, validation_evidence: str) -> None:
        if actor.kind not in ("owner", "supervisor"):
            raise RegistryError("only the owner or the supervisor can enable a tool")
        if not validation_evidence.strip():
            raise RegistryError("enabling a tool requires validation evidence")
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE tools SET enabled = 1, enabled_at = ?, enabled_by = ? WHERE tool_id = ? AND version = ?",
                (to_utc_str(self.clock.now()), f"{actor.kind}:{actor.id}", tool_id, version),
            )
            if cur.rowcount != 1:
                raise RegistryError("unknown tool")

    def disable(self, tool_id: str, version: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE tools SET enabled = 0 WHERE tool_id = ? AND version = ?", (tool_id, version)
            )

    def resolve(self, tool_id: str, version: str) -> tuple[ToolManifest, ToolAdapter]:
        """Return the enabled manifest and adapter; raise if unknown, disabled or tampered."""
        row = self.conn.execute(
            "SELECT manifest_json, manifest_hash, enabled FROM tools WHERE tool_id = ? AND version = ?",
            (tool_id, version),
        ).fetchone()
        if row is None:
            raise RegistryError("tool is not registered")
        if not row["enabled"]:
            raise RegistryError("tool is registered but not enabled")
        bound = self._adapters.get((tool_id, version))
        if bound is None:
            raise RegistryError("no trusted adapter loaded for this tool")
        data = json.loads(row["manifest_json"])
        data["capabilities"] = tuple(data["capabilities"])
        data["purchase_fields"] = tuple(data["purchase_fields"])
        manifest = ToolManifest(**data)
        if manifest.manifest_hash != row["manifest_hash"] or bound[0] != row["manifest_hash"]:
            raise RegistryError("manifest hash mismatch; refusing to run")
        return manifest, bound[1]
