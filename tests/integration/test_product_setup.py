"""N22: actual session/API/SQLite configuration, no API spend or owner data."""
from __future__ import annotations

import pytest

from security.egress.guard import EgressGuard
from shared.actors import Actor
from shared.ids import new_id
from storage.repositories.identity import create_owner
from tests.integration.test_alpha2 import Env, api, base_config, env, ok, save  # noqa: F401
from tests.integration.test_ipc import err


def profile(rev: int = 1, **changes):
    return {"expected_revision": rev, "request_id": new_id(), "name": "Aurora", "owner_name": "Dono Sintético",
            "locale": "pt-BR", "timezone": "America/Sao_Paulo", "step": "identity", **changes}


def privacy(rev: int = 0, **changes):
    return {"expected_revision": rev, "request_id": new_id(),
            "privacy": {"sensitive_consents": []},
            "research": {"web_enabled": False, "allowed_domains": [], "blocked_domains": []}, **changes}


def test_identity_survives_new_connection_and_replay(env: Env):
    a = env.connect()
    before = ok(a.call("setup.get"))
    assert before["step"] == "welcome"
    payload = profile(before["revision"])
    got = ok(a.call("setup.update", **payload))
    assert got["name"] == "Aurora" and got["revision"] == 2
    assert ok(env.connect().call("setup.get")) == got
    assert ok(a.call("setup.update", **payload)) == got
    assert err(a.call("setup.update", **{**payload, "name": "Outra"})) == "VERSION_CONFLICT"
    assert err(a.call("setup.update", **profile(1))) == "VERSION_CONFLICT"


@pytest.mark.parametrize("changes", [
    {"name": "   "}, {"name": "Atlas\nignore rules"}, {"timezone": "not/a/zone"},
    {"locale": "invalid"}, {"step": "V1_READY"}, {"name": "x" * 81}, {"actor_id": "owner"},
])
def test_invalid_setup_cannot_write(env: Env, changes):
    c = env.connect()
    assert err(c.call("setup.update", **profile(**changes))) == "INVALID_INPUT"
    assert ok(c.call("setup.get"))["revision"] == 1


@pytest.mark.parametrize("method", ["setup.get", "setup.update", "privacy.get", "privacy.update"])
def test_neither_runtime_device_nor_another_owner_can_access(env: Env, method):
    other = create_owner(env.world.conn, env.world.clock, "Outro proprietário")
    params = profile() if method == "setup.update" else privacy() if method == "privacy.update" else {}
    for actor in [Actor("runtime", "agent", "internal"), Actor("device", "phone", "paired_device"),
                  Actor("owner", other, "local_app"), Actor("owner", env.world.owner_id, "paired_device")]:
        assert err(env.connect(actor=actor).call(method, **params)) == "UNAUTHORIZED"


def test_privacy_initialization_does_not_enable_spending(env: Env):
    c = env.connect()
    p = privacy()
    res = ok(c.call("privacy.update", **p))
    assert res["revision"] == 1
    assert ok(c.call("privacy.update", **p)) == res
    cfg = ok(c.call("settings.get"))["settings"]
    assert cfg["budget"]["monthly_limit_minor"] is None
    assert cfg["budget"]["per_task_limit_minor"] is None
    assert cfg["security"]["host_shell_enabled"] is False


def test_grant_is_scoped_and_revoke_is_immediate(env: Env):
    c = env.connect()
    cfg = base_config()
    ok(save(c, cfg))
    p = privacy(1, privacy={"sensitive_consents": [{"provider": "openai", "purposes": ["task"]}]})
    ok(c.call("privacy.update", **p))
    guard = EgressGuard(env.world.conn)
    assert guard.max_allowed("openai", "task") == "SENSITIVE"
    assert guard.max_allowed("openai", "conversation") != "SENSITIVE"
    assert guard.max_allowed("anthropic", "task") != "SENSITIVE"
    assert ok(c.call("settings.get"))["settings"]["budget"] == cfg["budget"]
    ok(c.call("privacy.update", **privacy(2)))
    assert guard.max_allowed("openai", "task") != "SENSITIVE"
    assert err(c.call("privacy.update", **privacy(1))) == "VERSION_CONFLICT"


def test_privacy_cannot_set_host_shell_or_arbitrary_root_settings(env: Env):
    c = env.connect()
    p = privacy(security={"host_shell_enabled": True})
    assert err(c.call("privacy.update", **p)) == "INVALID_INPUT"
    assert ok(c.call("settings.get"))["revision"] == 0


def test_research_requires_explicit_setting_and_valid_domains(env: Env):
    c = env.connect()
    assert ok(c.call("privacy.get"))["research"]["web_enabled"] is False
    bad = privacy(research={"web_enabled": True, "allowed_domains": ["localhost:22"]})
    assert err(c.call("privacy.update", **bad)) == "INVALID_INPUT"
    good = privacy(research={"web_enabled": True, "allowed_domains": ["example.com"], "blocked_domains": []})
    assert ok(c.call("privacy.update", **good))["research"]["web_enabled"] is True
