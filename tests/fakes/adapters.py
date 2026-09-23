"""FAKE tool adapters and manifests for broker tests. They record "external effects" in memory so
tests can count exactly how many times something was sent. Synthetic destinations only."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from runtime.tools.registry import ToolManifest
from security.broker.broker import AdapterOutcome

MONEY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["amount_minor", "currency"],
    "properties": {"amount_minor": {"type": "integer", "minimum": 0}, "currency": {"type": "string"}},
}


def closed(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required or list(props),
        "properties": props,
    }


OWNER_SEND = ToolManifest(
    tool_id="messaging.send_owner_artifact",
    version="1.0.0",
    description="FAKE: deliver an artifact to the owner's verified channel",
    input_schema=closed({"recipient_ref": {"type": "string"}, "message": {"type": "string"}}),
    effect_class="EXTERNAL_WRITE",
    base_risk="R2",
    capabilities=("messaging.send",),
    network_policy="owner_channel",
    destination_field="recipient_ref",
    supports_idempotency_key=True,
    verification="provider_receipt",
)

EMAIL_SEND = ToolManifest(
    tool_id="email.send_external",
    version="1.0.0",
    description="FAKE: send an e-mail to a third party",
    input_schema=closed(
        {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}
    ),
    effect_class="EXTERNAL_WRITE",
    base_risk="R3",
    capabilities=("email.send",),
    network_policy="allowlist",
    destination_field="to",
    verification="provider_receipt",
)

PURCHASE = ToolManifest(
    tool_id="commerce.purchase",
    version="1.0.0",
    description="FAKE: buy an item from a sandbox store",
    input_schema=closed(
        {
            "vendor": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "total": MONEY_SCHEMA,
            "known_fees": {"type": "array", "items": MONEY_SCHEMA},
            "material_terms": {"type": "string"},
        }
    ),
    effect_class="IRREVERSIBLE",
    base_risk="R4",
    capabilities=("commerce.purchase",),
    network_policy="allowlist",
    destination_field="vendor",
    cost_field="total",
    cost_category="purchase",
    verification="provider_receipt",
    purchase_fields=("vendor", "items", "known_fees", "material_terms"),
)

PAID_SEARCH = ToolManifest(
    tool_id="research.paid_search",
    version="1.0.0",
    description="FAKE: paid public search API (read only, billable)",
    input_schema=closed({"query": {"type": "string"}, "max_cost": MONEY_SCHEMA}),
    effect_class="READ_ONLY",
    base_risk="R0",
    network_policy="allowlist",
    cost_field="max_cost",
    cost_category="paid_tool",
)

WORKSPACE_WRITE = ToolManifest(
    tool_id="workspace.write_file",
    version="1.0.0",
    description="FAKE: write a draft file in the workspace",
    input_schema=closed({"path": {"type": "string"}, "content": {"type": "string"}}),
    effect_class="LOCAL_WRITE",
    base_risk="R1",
)


@dataclass
class FakeWorld:
    """Records every simulated external effect."""

    sent: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    mode: str = "ok"  # ok | crash_after_send | no_receipt | fail_before_send | slow

    def adapter(self, kind: str):  # type: ignore[no-untyped-def]
        def run(tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
            if self.mode == "fail_before_send":
                return AdapterOutcome(
                    "FAILED", error_message="provider rejected request before sending", retryable=True
                )
            with self.lock:
                self.sent.append(
                    {"kind": kind, "input": dict(tool_input), "idempotency_key": ctx.idempotency_key}
                )
                n = len(self.sent)
            if self.mode == "crash_after_send":
                raise ConnectionError("connection dropped after submit")
            if self.mode == "no_receipt":
                return AdapterOutcome("SUCCEEDED")
            return AdapterOutcome(
                "SUCCEEDED", external_reference=f"fake-receipt-{n}", receipt={"n": n}, output={"echo": "ok"}
            )

        return run
