"""OpenAI Responses adapter against a CONTROLLED LOCAL HTTP SERVER (no network, no cost).

This proves the adapter's wire handling and error classification. It does NOT prove access to a
real account or model; that is the opt-in test in test_models.py (requires D-03).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from runtime.models.openai_responses import OpenAIResponsesProvider
from runtime.models.pricing import SPEC_REFERENCE_TABLE
from runtime.models.router import BudgetedModelClient, CatalogEntry, Consent, ModelRouter, Requirements
from runtime.models.types import (
    Billing,
    FinishReason,
    Message,
    ModelCapabilities,
    ModelRequest,
    ProviderCallError,
    ProviderErrorKind,
    Role,
    Usage,
)
from security.budget.budget import BudgetLimits, BudgetManager
from security.vault.vault import SecretValue
from storage.db import transaction
from tests.conftest import World
from tests.helpers import insert_task

FAKE_KEY = "sk-proj-" + "T" * 40  # atlas-scan: allow-fake-secret
CAPS = {
    "gpt-6-sol": ModelCapabilities(
        structured_output=True, tool_calls=True, streaming=True, effort_levels=("low", "medium", "high")
    )
}


def ok_body(text: str = "resposta sintetica", **extra: Any) -> dict[str, Any]:
    body = {
        "id": "resp_123",
        "model": "gpt-6-sol",
        "status": "completed",
        "output": [
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
        ],
        "usage": {"input_tokens": 120, "input_tokens_details": {"cached_tokens": 20}, "output_tokens": 30},
    }
    body.update(extra)
    return body


class FakeOpenAI:
    """Local stand-in for the API. Each test queues (status, headers, body|sse-events|'hang')."""

    def __init__(self) -> None:
        self.queue: list[tuple[int, dict[str, str], Any]] = []
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                outer.requests.append(
                    {
                        "path": self.path,
                        "method": self.command,
                        "auth": self.headers.get("Authorization"),
                        "body": json.loads(raw) if raw else None,
                    }
                )
                status, headers, body = outer.queue.pop(0) if outer.queue else (200, {}, ok_body())
                if isinstance(body, tuple) and body[0] == "gate":  # answer only when the test opens the gate
                    body[1].wait(10)
                    body = body[2]
                if body == "hang":
                    time.sleep(3)
                    return
                self.send_response(status)
                for k, v in {"x-request-id": "req_abc", **headers}.items():
                    self.send_header(k, v)
                if isinstance(body, list):  # SSE
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for event in body:
                        chunk = f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                        self.wfile.write(chunk.encode())
                        self.wfile.flush()
                    return
                payload = json.dumps(body).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _serve
            do_POST = _serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api() -> Iterator[FakeOpenAI]:
    fake = FakeOpenAI()
    yield fake
    fake.close()


def provider(api: FakeOpenAI) -> OpenAIResponsesProvider:
    return OpenAIResponsesProvider(
        lambda: SecretValue(FAKE_KEY.encode()), capabilities=CAPS, base_url=api.url
    )


def req(**kw: Any) -> ModelRequest:
    base: dict[str, Any] = {
        "model_id": "gpt-6-sol",
        "messages": (Message(Role.SYSTEM, "regras do produto"), Message(Role.USER, "compare as propostas")),
        "max_output_tokens": 200,
        "timeout_s": 2.0,
    }
    base.update(kw)
    return ModelRequest(**base)


def test_request_shape_and_successful_parse(api: FakeOpenAI) -> None:
    resp = provider(api).generate(
        req(json_schema={"type": "object", "properties": {}, "additionalProperties": False}, effort="low")
    )
    sent = api.requests[0]
    assert sent["path"] == "/v1/responses" and sent["method"] == "POST"
    assert sent["auth"] == f"Bearer {FAKE_KEY}"
    body = sent["body"]
    assert body["model"] == "gpt-6-sol" and body["store"] is False
    assert body["instructions"] == "regras do produto"
    assert body["input"] == [{"role": "user", "content": "compare as propostas"}]
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"] is True
    assert body["reasoning"] == {"effort": "low"}
    assert resp.output_text == "resposta sintetica"
    assert resp.usage == Usage(120, 20, 30)
    assert resp.request_id == "req_abc"
    assert resp.finish_reason == FinishReason.STOP


def test_refusal_function_call_and_incomplete(api: FakeOpenAI) -> None:
    p = provider(api)
    api.queue.append(
        (
            200,
            {},
            ok_body(
                output=[{"type": "message", "content": [{"type": "refusal", "refusal": "nao posso ajudar"}]}]
            ),
        )
    )
    assert p.generate(req()).finish_reason == FinishReason.CONTENT_FILTER
    api.queue.append(
        (
            200,
            {},
            ok_body(
                output=[
                    {
                        "type": "function_call",
                        "name": "email.send_external",
                        "arguments": '{"to": "x@example.test"}',
                        "call_id": "c1",
                    }
                ]
            ),
        )
    )
    r = p.generate(req())
    assert r.finish_reason == FinishReason.TOOL_CALL
    assert r.proposed_tool_calls == (
        {"name": "email.send_external", "arguments": {"to": "x@example.test"}, "call_id": "c1"},
    )
    api.queue.append(
        (200, {}, ok_body(status="incomplete", incomplete_details={"reason": "max_output_tokens"}))
    )
    assert p.generate(req()).finish_reason == FinishReason.LENGTH


@pytest.mark.parametrize(
    ("status", "kind", "billing"),
    [
        (400, ProviderErrorKind.INVALID_REQUEST, Billing.NONE),
        (401, ProviderErrorKind.AUTH, Billing.NONE),
        (404, ProviderErrorKind.MODEL_NOT_FOUND, Billing.NONE),
        (429, ProviderErrorKind.RATE_LIMITED, Billing.NONE),
        (500, ProviderErrorKind.UNAVAILABLE, Billing.UNKNOWN),
        (503, ProviderErrorKind.UNAVAILABLE, Billing.UNKNOWN),
    ],
)
def test_http_errors_are_normalized(
    api: FakeOpenAI, status: int, kind: ProviderErrorKind, billing: Billing
) -> None:
    api.queue.append((status, {"retry-after": "7"}, {"error": {"type": "synthetic", "message": "x"}}))
    r = provider(api).generate(req())
    assert r.error is not None and r.error.kind == kind and r.error.effective_billing == billing
    if status == 429:
        assert r.error.retry_after_s == 7.0


def test_timeout_is_sent_unknown(api: FakeOpenAI) -> None:
    api.queue.append((200, {}, "hang"))
    with pytest.raises(ProviderCallError) as e:
        provider(api).generate(req(timeout_s=0.5))
    assert e.value.sent is None


def test_connection_refused_is_proven_not_sent() -> None:
    p = OpenAIResponsesProvider(
        lambda: SecretValue(FAKE_KEY.encode()), capabilities=CAPS, base_url="http://127.0.0.1:9/v1"
    )
    with pytest.raises(ProviderCallError) as e:
        p.generate(req(timeout_s=10.0))  # Windows retries SYN for ~2 s before refusing
    assert e.value.sent is False


def test_streaming_yields_deltas_and_usage(api: FakeOpenAI) -> None:
    api.queue.append(
        (
            200,
            {},
            [
                {"type": "response.created"},
                {"type": "response.output_text.delta", "delta": "ola "},
                {"type": "response.output_text.delta", "delta": "mundo"},
                {"type": "response.completed", "response": ok_body()},
            ],
        )
    )
    p = provider(api)
    assert "".join(p.stream(req())) == "ola mundo"
    assert p.last_stream_usage == Usage(120, 20, 30)
    assert api.requests[0]["body"]["stream"] is True


def test_stream_error_event_raises(api: FakeOpenAI) -> None:
    api.queue.append((200, {}, [{"type": "response.output_text.delta", "delta": "x"}, {"type": "error"}]))
    with pytest.raises(ProviderCallError):
        list(provider(api).stream(req()))


def test_model_access_check_uses_free_metadata_call(api: FakeOpenAI) -> None:
    api.queue.append((200, {}, {"id": "gpt-6-sol", "object": "model"}))
    assert provider(api).check_model_access("gpt-6-sol") is True
    assert api.requests[0]["path"] == "/v1/models/gpt-6-sol" and api.requests[0]["method"] == "GET"
    api.queue.append((404, {}, {"error": {"type": "model_not_found"}}))
    assert provider(api).check_model_access("gpt-6-nonexistent") is False


def test_key_never_appears_in_logs_or_errors(api: FakeOpenAI, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    api.queue.append((401, {}, {"error": {"type": "invalid_api_key", "message": f"bad key {FAKE_KEY}"}}))
    r = provider(api).generate(req())
    assert r.error is not None and FAKE_KEY not in r.error.message
    assert FAKE_KEY not in caplog.text
    assert FAKE_KEY not in repr(provider(api).__dict__)


def test_plain_http_to_remote_hosts_is_refused() -> None:
    with pytest.raises(ValueError):
        OpenAIResponsesProvider(
            lambda: SecretValue(b"x" * 10), capabilities=CAPS, base_url="http://api.example.test/v1"
        )


def test_budgeted_client_end_to_end_with_local_server(api: FakeOpenAI, world: World) -> None:
    with transaction(world.conn):
        task_id = insert_task(world.conn, world.owner_id, world.employee.id)
    catalog = [CatalogEntry("openai", "gpt-6-sol", "general", 2, CAPS["gpt-6-sol"], True)]
    client = BudgetedModelClient(
        world.conn,
        world.clock,
        ModelRouter(catalog, Consent({"openai"})),
        {"openai": provider(api)},
        SPEC_REFERENCE_TABLE,
        BudgetManager(world.conn, world.clock, BudgetLimits("USD", 1_000, 500)),
    )
    resp = client.call(task_id=task_id, req=Requirements(), request=req())
    assert resp.output_text == "resposta sintetica"
    row = world.conn.execute("SELECT status, request_id FROM inference_attempts").fetchone()
    assert (row[0], row[1]) == ("SETTLED", "req_abc")


def test_cancel_inflight_marks_call_unknown(api: FakeOpenAI) -> None:
    api.queue.append((200, {}, "hang"))
    p = provider(api)
    threading.Timer(0.3, p.cancel_inflight).start()
    with pytest.raises(ProviderCallError) as e:
        p.generate(req(timeout_s=2.5))
    assert e.value.sent is None  # may already have been processed: billing unknown


def test_intelligence_check_flow_against_local_server(api: FakeOpenAI, tmp_path: Any) -> None:
    """Proves the check's logic (listing, budgeted call, schema validation, evidence) - not real access."""
    from runtime.models.intelligence_check import run_intelligence_check

    api.queue.append((200, {}, {"id": "gpt-6-sol", "object": "model"}))
    api.queue.append((200, {}, ok_body(text='{"ok": true, "word": "atlas"}')))
    report = run_intelligence_check(
        key_provider=lambda: SecretValue(FAKE_KEY.encode()),
        model_id="gpt-6-sol",
        max_cost_minor=5,
        base_url=api.url,
        workdir=tmp_path,
    )
    assert report.passed, report.to_json()
    assert report.request_id == "req_abc" and report.usage == {
        "input_tokens": 120,
        "cached_input_tokens": 20,
        "output_tokens": 30,
    }
    assert report.price_table_verified is False
    evidence = report.to_json()
    assert FAKE_KEY not in evidence and "Reply with JSON" not in evidence


def test_intelligence_check_refuses_unlisted_model_without_spending(api: FakeOpenAI, tmp_path: Any) -> None:
    from runtime.models.intelligence_check import run_intelligence_check

    api.queue.append((404, {}, {"error": {"type": "model_not_found"}}))
    report = run_intelligence_check(
        key_provider=lambda: SecretValue(FAKE_KEY.encode()),
        model_id="gpt-6-sol",
        max_cost_minor=5,
        base_url=api.url,
        workdir=tmp_path,
    )
    assert not report.passed and report.model_listed is False
    assert [r["path"] for r in api.requests] == ["/v1/models/gpt-6-sol"]  # no billable call was made
