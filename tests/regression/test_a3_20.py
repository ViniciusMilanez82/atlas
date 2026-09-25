"""A3-20 / T26: the API credential is bound to the configured endpoint; redirects never carry it.

Two CONTROLLED local HTTP servers on different origins and an exclusively synthetic key. The second
server records every request it receives: it must never see an Authorization header (in fact, the
adapter must not follow the redirect at all).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from runtime.models.openai_responses import DEFAULT_BASE_URL, OpenAIResponsesProvider, endpoint_problem
from runtime.models.types import Message, ModelCapabilities, ModelRequest, ProviderCallError, Role
from security.vault.vault import SecretValue

SYNTHETIC_KEY = "sk-test-" + "Z" * 32  # atlas-scan: allow-fake-secret
CAPS = {"gpt-6-sol": ModelCapabilities(structured_output=True)}


class Recorder:
    def __init__(self, redirect_to: str | None = None, status: int = 302) -> None:
        self.seen: list[dict[str, Any]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                return

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                outer.seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
                if redirect_to:
                    self.send_response(status)
                    self.send_header("Location", redirect_to + self.path)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = b'{"id": "gpt-6-sol", "status": "completed", "output": []}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _serve
            do_POST = _serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _provider(base: str) -> OpenAIResponsesProvider:
    return OpenAIResponsesProvider(
        lambda: SecretValue(SYNTHETIC_KEY.encode()), capabilities=CAPS, base_url=base
    )


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_to_another_origin_never_receives_the_credential(status: int) -> None:
    target = Recorder()
    origin = Recorder(redirect_to=target.url, status=status)
    try:
        p = _provider(origin.url + "/v1")
        req = ModelRequest("gpt-6-sol", (Message(Role.USER, "oi"),), max_output_tokens=16)
        try:
            resp = p.generate(req)
            assert resp.error is not None, "a redirected call must not look like a success"
        except ProviderCallError:
            pass
        with pytest.raises(ProviderCallError):
            p.check_model_access("gpt-6-sol")
        assert origin.seen and origin.seen[0]["auth"] == "Bearer " + SYNTHETIC_KEY  # configured origin only
        assert target.seen == [], f"redirect was followed: {target.seen}"  # before the fix: auth leaked
    finally:
        origin.close()
        target.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1.evil.test/v1",  # prefix that only looks like loopback
        "http://user:pass@127.0.0.1:8080/v1",  # userinfo
        "http://10.0.0.5/v1",  # plain HTTP to a non-loopback host
        "http://localhost:8080/v1",  # a name can resolve anywhere
        "ftp://127.0.0.1/v1",
        "https://api.openai.com.evil.test/v1",
    ],
)
def test_misleading_endpoints_are_rejected(url: str) -> None:
    assert endpoint_problem(url, allow_test_endpoints=True) is not None
    with pytest.raises(ValueError):
        _provider(url)


def test_production_mode_only_accepts_the_distribution_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_ALLOW_TEST_ENDPOINTS", raising=False)
    assert endpoint_problem(DEFAULT_BASE_URL, allow_test_endpoints=False) is None
    assert endpoint_problem("https://proxy.example.test/v1", allow_test_endpoints=False) is not None
    assert endpoint_problem("http://127.0.0.1:9999/v1", allow_test_endpoints=False) is not None
    with pytest.raises(ValueError):
        _provider("http://127.0.0.1:9999/v1")  # the test server is refused outside test mode


def test_exact_loopback_is_accepted_in_test_mode() -> None:
    assert endpoint_problem("http://127.0.0.1:8080/v1", allow_test_endpoints=True) is None
    assert endpoint_problem("http://[::1]:8080/v1", allow_test_endpoints=True) is None
