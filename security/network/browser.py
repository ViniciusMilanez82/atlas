"""Public browser-resource transport for a guest with NO network adapter.

Only bounded GET/HEAD requests are emitted, with freshly checked owner policy and
pinned public DNS/TLS. Guest cookies, authentication, arbitrary headers and request
bodies never enter the host request. This is public research, not an account browser.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from security.egress.guard import EgressGuard
from security.network.mediator import (
    NetworkMediator,
    NetworkRefused,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
)

MAX_RESOURCE = 600 * 1024
MAX_TOTAL = 20 * 1024 * 1024
RESOURCE_TYPES = ("text/", "image/", "font/", "application/javascript", "application/x-javascript",
                  "application/json", "application/xml", "application/xhtml+xml", "application/font-", "application/wasm")


class BrowserNetwork:
    def __init__(self, mediator: NetworkMediator, *, task_id: str | None, classification: str,
                 authorized: Callable[[], bool]) -> None:
        self.mediator, self.task_id, self.classification = mediator, task_id, classification
        self.authorized = authorized
        self.calls = 0
        self.total = 0
        self.receipts: list[str] = []
        self.documents: dict[str, dict[str, Any]] = {}
        self.deadline = time.monotonic() + 45

    def _policy(self, url: str) -> tuple[str, str, int, str]:
        if not self.authorized() or not self.mediator.enabled():
            raise NetworkRefused("browser research was stopped or is disabled")
        # Also retain the task's classification: encoding something in a URL never declassifies it.
        EgressGuard(self.mediator.conn).check(provider="web", purpose="browser", classification=self.classification)
        decoded = url
        for _ in range(4):
            self.mediator._check_outbound_data(decoded, "browser")
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        return self.mediator._check_url(url)

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        url = request.get("url")
        connection: http.client.HTTPConnection | None = None
        host = "invalid"
        try:
            if (set(request) != {"url", "method", "resource_type", "has_body"} or not isinstance(url, str)
                    or not 8 <= len(url) <= 2000 or request["method"] not in ("GET", "HEAD")
                    or request["has_body"] is not False or not isinstance(request["resource_type"], str)):
                raise NetworkRefused("browser sends public GET/HEAD only; forms, cookies and authentication are unavailable")
            self.calls += 1
            if self.calls > 80 or self.total >= MAX_TOTAL or time.monotonic() >= self.deadline:
                raise NetworkRefused("browser resource budget exhausted")
            scheme, host, port, path = self._policy(url)
            ip = self.mediator._resolve(host, port)
            if not self.authorized():
                raise NetworkRefused("browser permission changed during name resolution")
            cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
            connection = cls(host, ip, port, min(8.0, max(0.1, self.deadline - time.monotonic())))
            headers = {"User-Agent": "Atlas-Research/0.1", "Accept-Encoding": "identity", "Accept": "*/*"}
            connection.request(request["method"], path, headers=headers)
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "application/octet-stream")
            outgoing = [{"name": "Content-Type", "value": content_type}]
            if response.status in (301, 302, 303, 307, 308):
                location = urljoin(url, response.getheader("Location", ""))
                _, target_host, target_port, _ = self._policy(location)
                self.mediator._resolve(target_host, target_port)  # final hop is resolved/pinned AGAIN before dispatch
                outgoing.append({"name": "Location", "value": location})
                body = b""
            else:
                if not content_type.lower().startswith(RESOURCE_TYPES):
                    raise NetworkRefused("resource type not supported in the public research browser")
                chunks: list[bytes] = []
                length = 0
                while True:
                    if not self.authorized() or time.monotonic() >= self.deadline:
                        raise NetworkRefused("browser request was cancelled or expired")
                    block = response.read(min(65536, MAX_RESOURCE + 1 - length))
                    if not block:
                        break
                    length += len(block)
                    if length > MAX_RESOURCE or self.total + length > MAX_TOTAL:
                        raise NetworkRefused("browser resource is too large")
                    chunks.append(block)
                body = b"".join(chunks)
            # Re-read live permissions immediately before releasing bytes to the guest.
            self._policy(url)
            self.total += len(body)
            digest = hashlib.sha256(body).hexdigest()
            receipt = self.mediator._receipt(task_id=self.task_id, url=url, purpose="browser", decision="ALLOWED",
                                             reason="public research; no guest headers/cookies/body", status=response.status,
                                             ip=ip, nbytes=len(body), sha256=digest)
            self.receipts.append(receipt)
            if request["resource_type"] == "Document" and 200 <= response.status < 300:
                self.documents[url] = {"receipt": receipt, "sha256": digest, "content_type": content_type}
            return {"allowed": True, "status": response.status, "headers": outgoing,
                    "body": base64.b64encode(body).decode("ascii"), "receipt": receipt}
        except Exception as exc:
            # URL/query and arbitrary exception text can themselves carry secrets. Log only the host
            # and error type for a refused request; raw request bodies are not accepted in this API.
            try:
                host = urlsplit(url).hostname or "invalid" if isinstance(url, str) else "invalid"
                rid = self.mediator._receipt(task_id=self.task_id, url=f"https://{host}/", purpose="browser",
                                            decision="REFUSED", reason=type(exc).__name__)
                self.receipts.append(rid)
            except Exception:
                logging.getLogger(__name__).warning("Could not record refused browser request; request remains blocked")
            return {"allowed": False, "reason": "request refused by the host's current research policy"}
        finally:
            if connection is not None:
                connection.close()
