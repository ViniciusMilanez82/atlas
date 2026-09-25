"""OpenAI Responses API adapter (spec 6.4, 7.3; review Etapa 2).

Wire format checked against the official documentation on 2026-09-23:
* ``POST {base}/responses`` with ``Authorization: Bearer <key>``;
* body: ``model``, ``instructions`` (system text), ``input`` (role/content messages),
  ``max_output_tokens``, ``store``, optional ``reasoning: {"effort": ...}``, optional structured
  output as ``text: {"format": {"type": "json_schema", "name", "schema", "strict": true}}``;
* response: ``id``, ``status``, ``output[]`` items (``message`` with ``content[]`` of
  ``output_text``/``refusal``; ``function_call`` with ``name``, ``arguments``, ``call_id``),
  ``incomplete_details.reason``, ``usage.input_tokens``, ``usage.input_tokens_details.cached_tokens``,
  ``usage.output_tokens``; request id in the ``x-request-id`` header;
* streaming (``stream: true``): SSE events ``response.output_text.delta`` (``delta``),
  ``response.completed`` (full ``response``), ``error``.

Model IDs, capabilities and prices are NOT derived here: they come from configuration and must be
validated against the owner's account. Function calls in the output are returned only as
*proposals* - the broker is the only component that dispatches tools. The API key is obtained per
call from a trusted provider callable (Vault in production), never stored on the adapter, never
logged and never included in error messages.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from http.client import HTTPException, HTTPResponse
from typing import Any

from runtime.models.types import (
    Billing,
    FinishReason,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ProviderCallError,
    ProviderError,
    ProviderErrorKind,
    Role,
    Usage,
)
from security.vault.vault import SecretValue

DEFAULT_BASE_URL = "https://api.openai.com/v1"
# Distribution allowlist (spec 12.4): changing the endpoint is a trust configuration, not a model decision.
ALLOWED_ENDPOINTS = frozenset({DEFAULT_BASE_URL})
TEST_ENDPOINTS_ENV = "ATLAS_ALLOW_TEST_ENDPOINTS"


def test_endpoints_allowed() -> bool:
    """Test mode is an explicit environment switch set by the test harness, never by the app."""
    return os.environ.get(TEST_ENDPOINTS_ENV) == "1"


def endpoint_problem(url: str, *, allow_test_endpoints: bool) -> str | None:
    """Why ``url`` may not receive the API credential, or None when it may (A3-20).

    Parsed, not prefix-matched: scheme/host/port come from ``urlsplit``. No userinfo. Plain HTTP only
    to the exact loopback addresses 127.0.0.1 or ::1 and only in test mode. Remote (HTTPS) endpoints must
    be in the distribution allowlist in every mode.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return "endpoint is not a valid URL"
    del port
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "endpoint must not contain user information"
    host = parts.hostname or ""
    if parts.scheme == "https" and host:
        if url.rstrip("/") in ALLOWED_ENDPOINTS:  # remote endpoints: allowlist only, in every mode
            return None
        return f"endpoint {parts.scheme}://{host} is not in the distribution allowlist"
    if parts.scheme == "http":
        try:
            loopback = ipaddress.ip_address(host).is_loopback and host in ("127.0.0.1", "::1")
        except ValueError:
            loopback = False
        if not loopback:
            return "plain HTTP is accepted only for the exact loopback address (127.0.0.1 or ::1)"
        return None if allow_test_endpoints else "local test endpoints are accepted only in test mode"
    return f"unsupported endpoint scheme {parts.scheme!r}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Authenticated calls never follow redirects: the credential is bound to the configured origin."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
_STATUS_KIND = {
    **{code: ProviderErrorKind.INVALID_REQUEST for code in (301, 302, 303, 307, 308)},
    400: ProviderErrorKind.INVALID_REQUEST,
    401: ProviderErrorKind.AUTH,
    403: ProviderErrorKind.AUTH,
    404: ProviderErrorKind.MODEL_NOT_FOUND,
    422: ProviderErrorKind.INVALID_REQUEST,
    429: ProviderErrorKind.RATE_LIMITED,
}


class OpenAIResponsesProvider:
    provider_id = "openai"

    def __init__(
        self,
        key_provider: Callable[[], SecretValue],
        *,
        capabilities: dict[str, ModelCapabilities],
        base_url: str = DEFAULT_BASE_URL,
        allow_test_endpoints: bool | None = None,
    ) -> None:
        allowed = test_endpoints_allowed() if allow_test_endpoints is None else allow_test_endpoints
        problem = endpoint_problem(base_url, allow_test_endpoints=allowed)
        if problem:
            raise ValueError(f"refusing provider endpoint: {problem}")
        self._key_provider = key_provider
        self._caps = capabilities
        self._base = base_url.rstrip("/")
        self._inflight: set[HTTPResponse] = set()
        self._lock = threading.Lock()
        self.last_stream_usage: Usage | None = None

    # ------------------------------------------------------------------ contract

    def capabilities(self, model_id: str) -> ModelCapabilities:
        return self._caps.get(model_id, ModelCapabilities())

    def estimate_usage(self, request: ModelRequest) -> Usage:
        """Conservative upper bound (about 2 characters per token) for budget reservation."""
        chars = sum(len(m.content) for m in request.messages) + len(json.dumps(request.json_schema or {}))
        return Usage(max(1, chars // 2 + 16), 0, request.max_output_tokens)

    def health(self) -> bool:
        try:
            self._request("GET", "/models", None, timeout=10).close()
            return True
        except (ProviderCallError, _HTTPFailure):
            return False

    def check_model_access(self, model_id: str, timeout: float = 15.0) -> bool:
        """Free metadata call: does this account see the model? Not a substitute for a real call."""
        try:
            resp = self._request("GET", f"/models/{model_id}", None, timeout=timeout)
        except _HTTPFailure as failure:
            if failure.status == 404:
                return False
            kind = _STATUS_KIND.get(failure.status, ProviderErrorKind.UNAVAILABLE)
            raise ProviderCallError(
                f"model check failed: HTTP {failure.status}", sent=False, kind=kind
            ) from None
        with resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("id") == model_id)

    def cancel(self, request_id: str) -> None:
        """Synchronous requests have no server-side cancel: close the connection instead. The caller
        must treat the outcome and billing as unknown (the request may already have been processed)."""
        self.cancel_inflight()

    def cancel_inflight(self) -> None:
        with self._lock:
            for resp in list(self._inflight):
                try:
                    resp.close()
                    if resp.fp is not None:
                        resp.fp.close()
                except Exception:  # noqa: S110 - best effort close
                    pass

    def generate(self, request: ModelRequest) -> ModelResponse:
        body = self._body(request, stream=False)
        try:
            resp = self._request("POST", "/responses", body, timeout=request.timeout_s)
        except _HTTPFailure as failure:
            return self._error_response(request, failure)
        request_id = resp.headers.get("x-request-id")
        with self._lock:
            self._inflight.add(resp)
        try:
            raw = resp.read()
        except (TimeoutError, OSError, ValueError) as exc:
            raise ProviderCallError(
                "connection lost while reading the response",
                sent=None,
                kind=self._cancel_or_unavailable(resp),
            ) from exc
        finally:
            with self._lock:
                self._inflight.discard(resp)
            resp.close()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderCallError("provider returned invalid JSON", sent=None) from exc
        return self._parse(request, data, request_id or data.get("id"))

    def stream(self, request: ModelRequest) -> Iterator[str]:
        """Yield text deltas. Usage from ``response.completed`` is left in ``last_stream_usage``."""
        self.last_stream_usage = None
        body = self._body(request, stream=True)
        try:
            resp = self._request("POST", "/responses", body, timeout=request.timeout_s)
        except _HTTPFailure as failure:
            err = self._error_response(request, failure).error
            assert err is not None
            raise ProviderCallError(
                err.message, sent=False if err.effective_billing == Billing.NONE else None, kind=err.kind
            ) from None
        with self._lock:
            self._inflight.add(resp)
        try:
            event = None
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    kind = payload.get("type", event)
                    if kind == "response.output_text.delta":
                        yield str(payload.get("delta", ""))
                    elif kind == "response.completed":
                        self.last_stream_usage = self._usage(payload.get("response", {}).get("usage"))
                    elif kind in ("error", "response.failed"):
                        raise ProviderCallError("provider reported an error during streaming", sent=None)
        except (TimeoutError, OSError, ValueError) as exc:
            raise ProviderCallError(
                "stream interrupted", sent=None, kind=self._cancel_or_unavailable(resp)
            ) from exc
        finally:
            with self._lock:
                self._inflight.discard(resp)
            resp.close()

    # ------------------------------------------------------------------ internals

    def _cancel_or_unavailable(self, resp: HTTPResponse) -> ProviderErrorKind:
        return ProviderErrorKind.CANCELLED if resp.isclosed() else ProviderErrorKind.UNAVAILABLE

    @staticmethod
    def _body(request: ModelRequest, *, stream: bool) -> dict[str, Any]:
        system = [m.content for m in request.messages if m.role == Role.SYSTEM]
        body: dict[str, Any] = {
            "model": request.model_id,
            "input": [
                {"role": m.role.value, "content": m.content}
                for m in request.messages
                if m.role != Role.SYSTEM
            ],
            "max_output_tokens": request.max_output_tokens,
            "store": False,  # Atlas keeps its own state; nothing is left server-side by default
        }
        if system:
            body["instructions"] = "\n\n".join(system)
        if request.json_schema is not None:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "atlas_output",
                    "schema": request.json_schema,
                    "strict": True,
                }
            }
        if request.effort is not None:
            body["reasoning"] = {"effort": request.effort}
        if stream:
            body["stream"] = True
        return body

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None, *, timeout: float
    ) -> HTTPResponse:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self._base + path, data=data, method=method)  # noqa: S310 - scheme checked
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + self._key_provider().reveal().decode("utf-8"))
        try:
            return _OPENER.open(req, timeout=timeout)  # type: ignore[no-any-return]
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:  # redirect refused: never re-send the credential elsewhere
                raise _HTTPFailure(exc.code, exc.headers.get("x-request-id"), None, "redirect_refused") from None
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", {})
            except Exception:
                detail = {}
            raise _HTTPFailure(
                exc.code,
                exc.headers.get("x-request-id"),
                exc.headers.get("retry-after"),
                str(detail.get("type") or detail.get("code") or ""),
            ) from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
                raise ProviderCallError(f"could not connect ({type(reason).__name__})", sent=False) from None
            raise ProviderCallError(f"transport error ({type(reason).__name__})", sent=None) from None
        except TimeoutError as exc:
            raise ProviderCallError("timed out waiting for the provider", sent=None) from exc
        except (HTTPException, OSError) as exc:
            # e.g. the server closed the connection without a response: it may have been processed.
            raise ProviderCallError(f"transport error ({type(exc).__name__})", sent=None) from None

    def _error_response(self, request: ModelRequest, failure: _HTTPFailure) -> ModelResponse:
        kind = _STATUS_KIND.get(failure.status, ProviderErrorKind.UNAVAILABLE)
        if failure.status == 400 and failure.error_type in ("content_policy_violation",):
            kind = ProviderErrorKind.POLICY
        retry_after = None
        if failure.retry_after:
            try:
                retry_after = float(failure.retry_after)
            except ValueError:
                retry_after = None
        message = f"HTTP {failure.status}" + (f" ({failure.error_type})" if failure.error_type else "")
        return ModelResponse(
            self.provider_id,
            request.model_id,
            failure.request_id,
            "",
            finish_reason=FinishReason.ERROR,
            error=ProviderError(kind, message, retry_after),
        )

    @staticmethod
    def _usage(raw: dict[str, Any] | None) -> Usage | None:
        if not raw:
            return None
        cached = int((raw.get("input_tokens_details") or {}).get("cached_tokens") or 0)
        return Usage(int(raw.get("input_tokens", 0)), cached, int(raw.get("output_tokens", 0)))

    def _parse(self, request: ModelRequest, data: dict[str, Any], request_id: str | None) -> ModelResponse:
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        refused = False
        for item in data.get("output") or []:
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        texts.append(str(part.get("text", "")))
                    elif part.get("type") == "refusal":
                        refused = True
            elif item.get("type") == "function_call":
                try:
                    args: Any = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_unparsed": item.get("arguments")}
                calls.append({"name": item.get("name"), "arguments": args, "call_id": item.get("call_id")})
        usage = self._usage(data.get("usage"))
        status = data.get("status")
        reason = (data.get("incomplete_details") or {}).get("reason")
        if data.get("error"):
            return ModelResponse(
                self.provider_id,
                str(data.get("model", request.model_id)),
                request_id,
                "",
                finish_reason=FinishReason.ERROR,
                usage=usage,
                error=ProviderError(
                    ProviderErrorKind.UNAVAILABLE,
                    "provider reported a failed response",
                    billing=Billing.CHARGED if usage else Billing.UNKNOWN,
                ),
            )
        if refused:
            finish = FinishReason.CONTENT_FILTER
        elif status == "incomplete" and reason == "max_output_tokens":
            finish = FinishReason.LENGTH
        elif status == "incomplete" and reason == "content_filter":
            finish = FinishReason.CONTENT_FILTER
        elif calls:
            finish = FinishReason.TOOL_CALL
        else:
            finish = FinishReason.STOP
        return ModelResponse(
            self.provider_id,
            str(data.get("model", request.model_id)),
            request_id,
            "".join(texts),
            tuple(calls),
            finish,
            usage,
        )


class _HTTPFailure(Exception):
    def __init__(self, status: int, request_id: str | None, retry_after: str | None, error_type: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.request_id = request_id
        self.retry_after = retry_after
        self.error_type = error_type
