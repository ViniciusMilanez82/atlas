"""AT-007.1 / spec 10.1: trusted registry; the adapter's claims are validated, not trusted blindly."""

from __future__ import annotations

import dataclasses

import pytest

from runtime.tools.registry import RegistryError, ToolRegistry
from shared.actors import Actor
from storage.db import transaction
from tests.conftest import World
from tests.fakes.adapters import EMAIL_SEND, OWNER_SEND, PURCHASE, WORKSPACE_WRITE


def noop(tool_input: dict[str, object], ctx: object) -> dict[str, object]:
    return {"status": "SUCCEEDED"}


def test_new_tool_starts_disabled(world: World) -> None:
    reg = ToolRegistry(world.conn, world.clock)
    reg.register(WORKSPACE_WRITE, noop)
    with pytest.raises(RegistryError, match="not enabled"):
        reg.resolve(WORKSPACE_WRITE.tool_id, "1.0.0")
    reg.enable(WORKSPACE_WRITE.tool_id, "1.0.0", actor=world.owner, validation_evidence="tests passed")
    manifest, _ = reg.resolve(WORKSPACE_WRITE.tool_id, "1.0.0")
    assert manifest == WORKSPACE_WRITE


def test_unregistered_tool_does_not_run(world: World) -> None:
    with pytest.raises(RegistryError, match="not registered"):
        ToolRegistry(world.conn, world.clock).resolve("host.shell", "1.0.0")


def test_runtime_cannot_enable_tools(world: World) -> None:
    reg = ToolRegistry(world.conn, world.clock)
    reg.register(WORKSPACE_WRITE, noop)
    with pytest.raises(RegistryError):
        reg.enable(WORKSPACE_WRITE.tool_id, "1.0.0", actor=Actor("runtime", "rt"), validation_evidence="x")
    with pytest.raises(RegistryError):
        reg.enable(WORKSPACE_WRITE.tool_id, "1.0.0", actor=world.owner, validation_evidence="  ")


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"capabilities": ("host.shell",)}, "forbidden"),
        ({"capabilities": ("secret.read",)}, "forbidden"),
        ({"capabilities": ("policy.write",)}, "forbidden"),
        ({"capabilities": ("browser.personal_profile",)}, "forbidden"),
        ({"base_risk": "R5"}, "R5"),
        (
            {"effect_class": "READ_ONLY", "base_risk": "R0", "destination_field": None},
            "cannot declare itself",
        ),
        ({"base_risk": "R1"}, "requires at least R2"),
        ({"destination_field": None}, "destination"),
        ({"tool_id": "Send Email"}, "lowercase"),
        ({"input_schema": {"type": "object"}}, "closed object"),
    ],
)
def test_inconsistent_or_forbidden_manifest_rejected(
    world: World, change: dict[str, object], match: str
) -> None:
    bad = dataclasses.replace(EMAIL_SEND, **change)  # type: ignore[arg-type]
    with pytest.raises(RegistryError, match=match):
        ToolRegistry(world.conn, world.clock).register(bad, noop)


def test_email_tool_cannot_pretend_to_be_read_only(world: World) -> None:
    """Spec 10.1: a tool that sends e-mail cannot declare itself read-only."""
    liar = dataclasses.replace(OWNER_SEND, effect_class="READ_ONLY", base_risk="R0")
    with pytest.raises(RegistryError):
        ToolRegistry(world.conn, world.clock).register(liar, noop)


def test_purchase_must_be_irreversible_r4(world: World) -> None:
    weak = dataclasses.replace(PURCHASE, effect_class="EXTERNAL_WRITE", base_risk="R3")
    with pytest.raises(RegistryError, match="IRREVERSIBLE"):
        ToolRegistry(world.conn, world.clock).register(weak, noop)


def test_tampered_manifest_refused(world: World) -> None:
    reg = ToolRegistry(world.conn, world.clock)
    reg.register(OWNER_SEND, noop)
    reg.enable(OWNER_SEND.tool_id, "1.0.0", actor=world.owner, validation_evidence="ok")
    with transaction(world.conn):
        world.conn.execute(
            "UPDATE tools SET manifest_json = replace(manifest_json, '\"R2\"', '\"R0\"') WHERE tool_id = ?",
            (OWNER_SEND.tool_id,),
        )
    with pytest.raises(RegistryError, match="hash mismatch"):
        reg.resolve(OWNER_SEND.tool_id, "1.0.0")


def test_same_version_cannot_change_manifest(world: World) -> None:
    reg = ToolRegistry(world.conn, world.clock)
    reg.register(OWNER_SEND, noop)
    with pytest.raises(RegistryError, match="different manifest"):
        reg.register(dataclasses.replace(OWNER_SEND, description="changed"), noop)


def test_adapter_must_be_loaded(world: World) -> None:
    reg = ToolRegistry(world.conn, world.clock)
    reg.register(OWNER_SEND, noop)
    reg.enable(OWNER_SEND.tool_id, "1.0.0", actor=world.owner, validation_evidence="ok")
    fresh = ToolRegistry(world.conn, world.clock)  # e.g. after restart, before adapters load
    with pytest.raises(RegistryError, match="no trusted adapter"):
        fresh.resolve(OWNER_SEND.tool_id, "1.0.0")
