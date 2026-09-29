"""Real local HTTP, IPC and SQLite; no production credentials or model costs."""
from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from tests.integration.test_alpha2 import (  # noqa: F401 - fixtures
    FAKE_KEY,
    Env,
    api,
    base_config,
    configure_intelligence,
    env,
    ok,
    save,
    send,
)
from tests.integration.test_openai_adapter import FakeOpenAI, ok_body


def key(c: Any, value: str = FAKE_KEY) -> None:
    ok(c.call("credentials.register", provider="openai", secret_b64=base64.b64encode(value.encode()).decode()))


def check(c: Any) -> dict[str, Any]:
    return ok(c.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=5))["report"]


def test_saved_key_is_distinguished_from_missing_settings(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    key(c)
    details = env.make().intelligence.connection_details()
    assert ok(c.call("system.health"))["intelligence_reason"].startswith("SETTINGS_MISSING:")
    assert details["credential_registered"] is True
    assert details["reason_code"] == "SETTINGS_MISSING"
    assert FAKE_KEY not in json.dumps(details)
    assert api.requests == []


def test_price_consent_and_validation_are_separate(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    key(c)
    ok(save(c, base_config()))
    assert env.make().intelligence.connection_details()["reason_code"] == "PRICE_CONSENT_REQUIRED"
    ok(save(c, base_config(accept_reference_prices=True)))
    assert env.make().intelligence.connection_details()["reason_code"] == "VALIDATION_REQUIRED"
    assert api.requests == []


def test_check_leaves_room_for_reasoning_and_verifies_exact_word(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    body = api.requests[-1]["body"]
    assert body["max_output_tokens"] >= 2048
    assert body["reasoning"] == {"effort": "low"}
    assert env.make().intelligence.connection_details()["reason_code"] == "READY"
    api.queue.extend([(200, {}, {"id": "gpt-6-sol"}), (200, {}, ok_body('{"ok":true,"word":"wrong"}'))])
    assert check(c)["passed"] is False


@pytest.mark.parametrize(("status", "error_code", "expected"), [
    (401, "invalid_api_key", "API_AUTH_REJECTED"),
    (403, "permission_denied", "API_ACCESS_DENIED"),
    (404, "model_not_found", "MODEL_NOT_AVAILABLE"),
    (429, "insufficient_quota", "API_QUOTA_EXHAUSTED"),
    (429, "credit_balance_exhausted", "API_QUOTA_EXHAUSTED"),
    (429, "project_spend_limit_exceeded", "API_QUOTA_EXHAUSTED"),
    (429, "rate_limit_exceeded", "API_RATE_LIMIT"),
])
def test_model_lookup_failure_is_useful_and_keeps_key(env: Env, api: FakeOpenAI, status: int, error_code: str, expected: str) -> None:
    c = env.connect()
    key(c)
    ok(save(c, base_config(accept_reference_prices=True)))
    api.queue.append((status, {}, {"error": {"code": error_code, "type": "invalid_request_error", "message": FAKE_KEY}}))
    report = check(c)
    assert report["passed"] is False
    assert report["reason_code"] == expected
    assert FAKE_KEY not in json.dumps(report)
    state = env.make().intelligence.connection_details()
    assert ok(c.call("system.health"))["intelligence_reason"].startswith(expected + ":")
    assert state["credential_registered"] is True
    assert state["reason_code"] == expected
    assert len(api.requests) == 1
    assert env.world.conn.execute("SELECT COUNT(*) FROM inference_attempts").fetchone()[0] == 0


def test_incomplete_response_never_enables_conversation(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    key(c)
    ok(save(c, base_config(accept_reference_prices=True)))
    api.queue.extend([(200, {}, {"id": "gpt-6-sol"}), (200, {}, ok_body('{"ok":true,"word":"atlas"}', status="incomplete", incomplete_details={"reason":"max_output_tokens"}))])
    report = check(c)
    assert not report["passed"]
    assert report["reason_code"] == "OUTPUT_LIMIT_REACHED"
    assert env.world.conn.execute("SELECT status FROM inference_attempts").fetchone()[0] == "SETTLED"


def test_missing_usage_is_not_validated_from_budget_estimate(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    key(c)
    ok(save(c, base_config(accept_reference_prices=True)))
    api.queue.extend([(200, {}, {"id": "gpt-6-sol"}), (200, {}, ok_body('{"ok":true,"word":"atlas"}', usage=None))])
    report = check(c)
    assert not report["passed"]
    assert report["reason_code"] == "USAGE_MISSING"


def test_blank_or_bad_header_key_does_not_destroy_working_key(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    refs_before = env.world.conn.execute("SELECT COUNT(*) FROM credential_refs WHERE revoked_at IS NULL").fetchone()[0]
    for value in (" \n\t", "sk-valid\r\nInjected: secret", "sk-\u2603"):
        result = c.call("credentials.register", provider="openai", secret_b64=base64.b64encode(value.encode()).decode())
        assert "error" in result
        assert ok(c.call("settings.get"))["intelligence"]["configured"] is True
    assert env.world.conn.execute("SELECT COUNT(*) FROM credential_refs WHERE revoked_at IS NULL").fetchone()[0] == refs_before


def test_surrounding_paste_whitespace_is_trimmed_without_echo(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    key(c, " \n" + FAKE_KEY + "\r\n")
    ok(save(c, base_config(accept_reference_prices=True)))
    api.queue.extend([(200, {}, {"id": "gpt-6-sol"}), (200, {}, ok_body('{"ok":true,"word":"atlas"}'))])
    assert check(c)["passed"]
    assert api.requests[0]["auth"] == "Bearer " + FAKE_KEY


def test_authorized_check_followed_by_real_conversation_route(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    configure_intelligence(c, api)
    conv = ok(c.call("conversations.current"))["conversation_id"]
    api.queue.append((200, {}, ok_body('{"intent":"chat","reply":"Olá, conexão de teste funcionando.","objective":""}')))
    result = send(c, env, conv, "Oi, como você está?")
    assert result["reply"]["content"] == "Olá, conexão de teste funcionando."
    assert result["task_id"] is None
    assert api.requests[-1]["path"] == "/v1/responses"


def test_unsupported_default_does_not_prevent_testing_supported_profile(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    key(c)
    cfg = base_config(accept_reference_prices=True)
    cfg["intelligence"]["profiles"]["general"]["model_id"] = "unpriced-model"
    cfg["intelligence"]["profiles"]["light"]["model_id"] = "gpt-6-sol"
    ok(save(c, cfg))
    api.queue.extend([(200, {}, {"id": "gpt-6-sol"}), (200, {}, ok_body('{"ok":true,"word":"atlas"}'))])
    assert check(c)["passed"]
    # Does not silently replace the selected default. Owner still chooses which profile to use.
    assert not ok(c.call("settings.get"))["intelligence"]["configured"]


def test_insufficient_local_cap_never_sends_generation(env: Env, api: FakeOpenAI) -> None:
    c = env.connect()
    key(c)
    ok(save(c, base_config(accept_reference_prices=True)))
    api.queue.append((200, {}, {"id": "gpt-6-sol"}))
    report = ok(c.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=1))["report"]
    assert not report["passed"]
    assert report["reason_code"] == "LOCAL_BUDGET_BLOCKED"
    assert [r["method"] for r in api.requests] == ["GET"]


def test_changed_key_cannot_inherit_inflight_validation(env: Env, api: FakeOpenAI, monkeypatch: Any) -> None:
    from runtime.models.openai_responses import OpenAIResponsesProvider
    c = env.connect()
    key(c)
    ok(save(c, base_config(accept_reference_prices=True)))
    original = OpenAIResponsesProvider.generate
    def rotate(p: Any, request: Any) -> Any:
        result = original(p, request)
        key(env.connect(), "sk-proj-" + "B" * 40)
        return result
    monkeypatch.setattr(OpenAIResponsesProvider, "generate", rotate)
    api.queue.extend([(200, {}, {"id": "gpt-6-sol"}), (200, {}, ok_body('{"ok":true,"word":"atlas"}'))])
    report = check(c)
    assert not report["passed"]
    assert report["reason_code"] == "CONFIG_CHANGED"
    assert not ok(c.call("settings.get"))["intelligence"]["configured"]


@pytest.mark.parametrize("body", [[], None, {"error": {"code": {"unexpected": "shape"}}}])
def test_malformed_lookup_never_exposes_body_or_makes_model_call(env: Env, api: FakeOpenAI, body: Any) -> None:
    c = env.connect()
    key(c)
    ok(save(c, base_config(accept_reference_prices=True)))
    api.queue.append((200, {}, body))
    assert not check(c)["passed"]
    assert len(api.requests) == 1


def test_provider_quota_error_is_not_retried_on_other_validated_model(env: Env, api: FakeOpenAI) -> None:
    from runtime.models.router import Requirements
    from runtime.models.types import Message, ModelRequest, Role
    from shared.errors import AtlasError, ErrorCode
    from tests.integration.test_intelligence_modes import _setup
    c = env.connect()
    _setup(c, api, "automatic")
    before = len(api.requests)
    api.queue.append((429, {}, {"error": {"code": "project_spend_limit_exceeded", "type": "insufficient_quota"}}))
    with pytest.raises(AtlasError) as caught:
        env.make().intelligence.build_client().call(task_id=None, employee_id=env.world.employee.id,
            req=Requirements(structured_output=True), request=ModelRequest("gpt-6-sol", (Message(Role.USER, "synthetic"),), 100))
    assert caught.value.code == ErrorCode.BUDGET_EXCEEDED
    assert len(api.requests) == before + 1
