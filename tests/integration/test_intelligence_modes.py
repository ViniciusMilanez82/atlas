"""N13 / spec 11.2: the owner's mode really changes which VALIDATED model is called.

Three profiles (light/general/deep) validated against a CONTROLLED local server with a synthetic key; the
model id in each request that reached the server is asserted. This proves routing, not model quality or
access on a real account (D-03).
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from runtime.models.router import Requirements
from runtime.models.types import Message, ModelRequest, Role
from tests.conftest import World
from tests.integration.test_alpha2 import FAKE_KEY, base_config, ok, save
from tests.integration.test_openai_adapter import ok_body

MODELS = {"light": "gpt-6-luna", "general": "gpt-6-sol", "deep": "gpt-6-astra"}


def _setup(c: Any, api: Any, mode: str, validate: tuple[str, ...] = ("light", "general", "deep")) -> None:
    ok(
        c.call(
            "credentials.register", provider="openai", secret_b64=base64.b64encode(FAKE_KEY.encode()).decode()
        )
    )
    cfg = base_config(accept_reference_prices=True, monthly_limit_minor=10_000, per_task_limit_minor=5_000)
    cfg["intelligence"]["mode"] = mode
    cfg["intelligence"]["profiles"] = {k: {"provider": "openai", "model_id": v} for k, v in MODELS.items()}
    cfg["intelligence"]["default_profile"] = "general"
    ok(save(c, cfg))
    for profile in validate:
        model = MODELS[profile]
        api.queue.append((200, {}, {"id": model, "object": "model"}))
        api.queue.append((200, {}, ok_body(text='{"ok": true, "word": "atlas"}')))
        assert ok(c.call("intelligence.check", model_id=model, max_cost_minor=5))["report"]["passed"] is True


def _call(env: Any, world: World, api: Any, complexity: str) -> str:
    client = env.make().intelligence.build_client()
    api.queue.append((200, {}, ok_body(text="{}")))
    client.call(
        task_id=None,
        employee_id=world.employee.id,
        purpose="conversation",
        req=Requirements(structured_output=True, complexity=complexity),
        request=ModelRequest("auto", (Message(Role.USER, "oi"),), max_output_tokens=16),
    )
    return str(api.requests[-1]["body"]["model"])


@pytest.mark.parametrize(
    ("mode", "complexity", "expected"),
    [
        ("economic", "normal", "gpt-6-luna"),
        ("economic", "hard", "gpt-6-luna"),
        ("max_quality", "light", "gpt-6-astra"),
        ("automatic", "light", "gpt-6-luna"),
        ("automatic", "normal", "gpt-6-sol"),
        ("automatic", "hard", "gpt-6-astra"),
        ("manual", "hard", "gpt-6-sol"),  # manual = the default profile, whatever the complexity
    ],
)
def test_mode_changes_the_model_called(
    env: Any, api: Any, world: World, mode: str, complexity: str, expected: str
) -> None:
    c = env.connect()
    _setup(c, api, mode)
    assert _call(env, world, api, complexity) == expected


def test_unvalidated_profiles_are_never_used_and_are_listed(env: Any, api: Any, world: World) -> None:
    c = env.connect()
    _setup(c, api, "max_quality", validate=("general",))  # only the default profile was checked
    assert _call(env, world, api, "hard") == "gpt-6-sol"  # 'deep' exists in settings but is not validated
    profiles = ok(c.call("settings.get"))["intelligence"]["profiles"]
    state = {p["profile"]: p["validated"] for p in profiles}
    assert state == {
        "light": False,
        "general": True,
        "deep": False,
    }  # the UI can say what still needs a check
