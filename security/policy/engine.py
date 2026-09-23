"""Policy Engine (spec 11.1, ADR-004, AT-007.2).

Deterministic and independent of model output. Order of evaluation:
1. completeness and actor authentication (missing data -> DENY);
2. prohibitions and capability limits (R5, forbidden or disabled capabilities -> DENY);
3. task constraints (external writes / purchases not allowed by the task -> DENY);
4. data classification (SECRET never leaves; SENSITIVE and PERSONAL raise the risk);
5. risk defaults R0..R4 with owner channels and mandates.
Any exception inside the engine returns DENY (fail closed). A prohibition is never overridden
by a mandate, an approval or a low score elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from runtime.tools.registry import (
    FORBIDDEN_CAPABILITIES,
    RISK_ORDER,
    ToolManifest,
    risk_max,
)
from shared.actors import Actor
from shared.canonical import canonical_hash
from shared.money import Money

POLICY_SCHEMA = "1.0.0"


class Outcome(StrEnum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


@dataclass(frozen=True)
class PolicyRules:
    """Owner-adjustable rules. Changing them changes policy_version (audited)."""

    code_network_enabled: bool = False  # spec 7.5 unreviewed_code_network_enabled (pinned false in V1)
    host_shell_enabled: bool = False  # pinned false; kept only to prove it cannot be turned on
    dispatch_actor_kinds: tuple[str, ...] = ("worker", "owner")
    mandate_eligible_max_risk: str = "R3"  # R4 always needs a fresh, strong approval

    def version(self) -> str:
        digest = canonical_hash(
            {
                "schema": POLICY_SCHEMA,
                **self.__dict__,
                "dispatch_actor_kinds": list(self.dispatch_actor_kinds),
            }
        )
        return f"policy-{POLICY_SCHEMA}+{digest[:12]}"


@dataclass(frozen=True)
class MandateView:
    mandate_id: str
    max_risk: str


@dataclass(frozen=True)
class PolicyRequest:
    actor: Actor
    manifest: ToolManifest | None
    destination: str | None
    data_classification: str | None
    cost: Money | None
    task_constraints: dict[str, Any] | None
    owner_channels: frozenset[str] = frozenset()
    mandate: MandateView | None = None


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason_code: str
    policy_version: str
    risk_class: str
    strong_confirmation: bool = False
    notes: tuple[str, ...] = field(default=())


class PolicyEngine:
    def __init__(self, rules: PolicyRules | None = None) -> None:
        self.rules = rules or PolicyRules()
        if self.rules.host_shell_enabled or self.rules.code_network_enabled:
            raise ValueError("V1 pins host_shell_enabled and code_network_enabled to false")
        self.version = self.rules.version()

    def evaluate(self, req: PolicyRequest) -> Decision:
        try:
            return self._evaluate(req)
        except Exception:  # fail closed on any internal error
            return Decision(Outcome.DENY, "ENGINE_ERROR", self.version, "R5")

    def _deny(self, code: str, risk: str = "R5") -> Decision:
        return Decision(Outcome.DENY, code, self.version, risk)

    def _evaluate(self, req: PolicyRequest) -> Decision:
        m = req.manifest
        # 1. completeness / authentication
        if m is None:
            return self._deny("UNKNOWN_TOOL")
        if req.task_constraints is None or req.data_classification is None:
            return self._deny("INCOMPLETE_INPUT")
        if req.actor.kind not in self.rules.dispatch_actor_kinds:
            return self._deny("ACTOR_NOT_ALLOWED")
        external = m.effect_class in ("EXTERNAL_WRITE", "IRREVERSIBLE")
        if external and not req.destination:
            return self._deny("MISSING_DESTINATION")

        # 2. prohibitions and capability limits
        caps = set(m.capabilities)
        if caps & FORBIDDEN_CAPABILITIES or m.base_risk == "R5":
            return self._deny("PROHIBITED_ACTION")
        if "code.network" in caps and not self.rules.code_network_enabled:
            return self._deny("CAPABILITY_DISABLED")

        # 3. task constraints
        if external and not req.task_constraints.get("external_writes", False):
            return self._deny("TASK_FORBIDS_EXTERNAL_WRITES", m.base_risk)
        if any(c.startswith("commerce.") for c in caps) and not req.task_constraints.get("purchases", False):
            return self._deny("TASK_FORBIDS_PURCHASES", m.base_risk)

        # 4. data classification
        risk = m.base_risk
        cls = req.data_classification
        notes: list[str] = []
        if external and cls == "SECRET":
            return self._deny("SECRET_DATA_EGRESS")
        if external and cls == "SENSITIVE":
            risk = RISK_ORDER[min(RISK_ORDER.index(risk) + 1, RISK_ORDER.index("R4"))]
            notes.append("sensitive data raised risk one level")
        if external and cls == "PERSONAL" and req.destination not in req.owner_channels:
            risk = risk_max(risk, "R3")
            notes.append("personal data to a third party is at least R3")

        # 5. defaults by risk
        if risk in ("R0", "R1"):
            return Decision(Outcome.ALLOW, "LOW_RISK", self.version, risk, notes=tuple(notes))
        if risk == "R2":
            if req.destination in req.owner_channels:
                return Decision(
                    Outcome.ALLOW, "OWNER_VERIFIED_CHANNEL", self.version, risk, notes=tuple(notes)
                )
            risk = "R3"
            notes.append("destination is not a verified owner channel")
        if risk == "R3":
            mand = req.mandate
            if mand is not None and RISK_ORDER.index(risk) <= RISK_ORDER.index(
                min(mand.max_risk, self.rules.mandate_eligible_max_risk, key=RISK_ORDER.index)
            ):
                return Decision(Outcome.ALLOW, "MANDATE_COVERS", self.version, risk, notes=tuple(notes))
            return Decision(Outcome.ASK, "APPROVAL_REQUIRED_R3", self.version, risk, notes=tuple(notes))
        if risk == "R4":
            return Decision(
                Outcome.ASK,
                "STRONG_APPROVAL_REQUIRED_R4",
                self.version,
                risk,
                strong_confirmation=True,
                notes=tuple(notes),
            )
        return self._deny("UNCLASSIFIED")


def activate(conn: Any, clock: Any, engine: PolicyEngine, actor: Actor) -> str:
    """Record the active policy version and its rules (audit trail for policy_version)."""
    import json

    from shared.clock import to_utc_str
    from storage.db import transaction

    with transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO policies(version, rules_json, activated_at, activated_by) VALUES (?,?,?,?)",
            (
                engine.version,
                json.dumps(
                    {
                        **engine.rules.__dict__,
                        "dispatch_actor_kinds": list(engine.rules.dispatch_actor_kinds),
                    },
                    sort_keys=True,
                ),
                to_utc_str(clock.now()),
                f"{actor.kind}:{actor.id}",
            ),
        )
    return engine.version
