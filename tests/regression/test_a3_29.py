"""A3-29 / T29: "Pronta" is bound to credential + endpoint + model + capability version.

Synthetic keys A and B against a CONTROLLED local server. Replacing the key, the endpoint or the model
removes "ready" immediately; a new (paid) check is required and goes through the global ledger.
"""

from __future__ import annotations

import base64
from typing import Any

from core.intelligence import IntelligenceSetup
from tests.conftest import World
from tests.integration.test_alpha2 import base_config, configure_intelligence, ok, save
from tests.integration.test_openai_adapter import FakeOpenAI

KEY_B = "sk-proj-" + "B" * 40  # atlas-scan: allow-fake-secret


def _status(c: Any) -> dict[str, Any]:
    return ok(c.call("settings.get"))["intelligence"]  # type: ignore[no-any-return]


def test_replacing_the_key_withdraws_ready(env: Any, api: Any) -> None:
    c = env.connect()
    configure_intelligence(c, api)  # key A validated
    assert _status(c)["configured"] is True
    ok(
        c.call(
            "credentials.register", provider="openai", secret_b64=base64.b64encode(KEY_B.encode()).decode()
        )
    )
    st = _status(c)
    assert st["configured"] is False, (
        "a check run with key A must not vouch for key B"
    )  # before the fix: two active refs, misleading "no API credential registered"
    assert "not validated" in st["reason"]
    checks = env.world.conn.execute(
        "SELECT COUNT(*) FROM inference_attempts WHERE purpose = 'intelligence_check'"
    ).fetchone()[0]
    assert checks == 1  # nothing was re-checked silently (a new check is a paid, owner-authorized action)


def test_changing_the_model_withdraws_ready(env: Any, api: Any) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    cfg = base_config(accept_reference_prices=True)
    cfg["intelligence"]["profiles"][cfg["intelligence"]["default_profile"]]["model_id"] = "gpt-6-luna"
    ok(save(c, cfg))
    assert _status(c)["configured"] is False


def test_changing_the_endpoint_withdraws_ready(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    other = FakeOpenAI()  # a different endpoint with the same stored key reference
    try:
        vault = env.make().intelligence.vault
        moved = IntelligenceSetup(world.conn, world.clock, vault, base_url=other.url)
        st = moved.status()
        assert st.configured is False
    finally:
        other.close()


def test_the_binding_is_recorded_with_the_check(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    row = world.conn.execute(
        "SELECT credential_ref, endpoint, model_id, capability_version FROM intelligence_validations"
    ).fetchone()
    assert row[0] and row[1] == env.base_url + "/responses" and row[2] == "gpt-6-sol" and row[3]
