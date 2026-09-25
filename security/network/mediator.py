"""Mediated network egress (N14 mediation part; spec 9.2, 15, 16). Contract v2: "não liberar NIC irrestrita".

Every outbound HTTP(S) request made on behalf of a task - today by the ``web.fetch`` tool, later by
the workspace VM through its proxy transport - passes through ``NetworkMediator``:

* only ``http``/``https`` to ports 80/443, no userinfo in the URL;
* the host is resolved ONCE and every address must be public (no loopback, private, link-local,
  metadata, multicast, reserved or CGNAT ranges); the connection is pinned to that address, so DNS
  rebinding cannot swap it afterwards (TLS still verifies the certificate for the host name);
* redirects are never followed automatically: each hop is re-checked like a new request (max 5);
* size and time limits; only textual content types;
* the URL itself is outbound data: the Egress Guard classifies it for purpose ``web`` and credential
  shapes or registered secrets in it block the request (sentinels never leave in a query string);
* optional per-owner allow/deny lists (``research.allowed_domains`` / ``blocked_domains``);
* every attempt - allowed or refused - gets a receipt in ``network_requests``.

Test mode (``ATLAS_ALLOW_TEST_ENDPOINTS=1``, set only by the test harness) additionally accepts plain
HTTP to the exact loopback address with any port, so local servers can stand in for the Internet.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import socket
import sqlite3
import ssl
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from security.egress.guard import EgressBlocked, EgressGuard
from security.egress.lineage import classify_text
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from shared.redaction import default_redactor
from storage.db import transaction

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 20.0
MAX_REDIRECTS = 5
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class NetworkRefused(AtlasError):
    def __init__(self, reason: str) -> None:
        super().__init__(ErrorCode.POLICY_DENIED, reason, persisted="nothing sent", recommended_action=
                         "use another public source or ask the owner")
        self.reason = reason


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    sha256: str
    receipts: list[str] = field(default_factory=list)

    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def test_mode() -> bool:
    return os.environ.get("ATLAS_ALLOW_TEST_ENDPOINTS") == "1"


def address_problem(ip: str) -> str | None:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.is_loopback:
        return "loopback address"
    if addr.is_link_local:
        return "link-local address (includes cloud metadata 169.254.169.254)"
    if addr.is_private:
        return "private network address"
    if addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return "reserved/multicast address"
    if isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT:
        return "carrier-grade NAT address"
    return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a pre-resolved address; the certificate is still checked against the host name."""

    def __init__(self, host: str, ip: str, port: int, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class NetworkMediator:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, *, resolver: Any = None) -> None:
        self.conn = conn
        self.clock = clock
        self.resolver = resolver or socket.getaddrinfo

    # ------------------------------------------------------------------ policy

    def _settings(self) -> dict[str, Any]:
        row = self.conn.execute("SELECT config_json FROM settings ORDER BY revision DESC LIMIT 1").fetchone()
        research: dict[str, Any] = (json.loads(row[0]).get("research") if row else None) or {}
        return research

    def enabled(self) -> bool:
        return bool(self._settings().get("web_enabled", False))

    def _check_url(self, url: str) -> tuple[str, str, int, str]:
        """Returns (scheme, host, port, path+query) or raises NetworkRefused."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise NetworkRefused("not a valid URL") from None
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise NetworkRefused("URLs with user information are refused")
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise NetworkRefused(f"only http(s) URLs are fetched, not {parts.scheme or '(none)'}")
        host = parts.hostname.lower().rstrip(".")
        port = port or (443 if parts.scheme == "https" else 80)
        loopback_test = test_mode() and parts.scheme == "http" and host in ("127.0.0.1", "::1")
        if port not in (80, 443) and not loopback_test:
            raise NetworkRefused(f"port {port} is not allowed (80/443 only)")
        research = self._settings()
        blocked = [d.lower() for d in research.get("blocked_domains", [])]
        allowed = [d.lower() for d in research.get("allowed_domains", [])]
        if any(host == d or host.endswith("." + d) for d in blocked):
            raise NetworkRefused(f"{host} is blocked by the owner")
        if allowed and not loopback_test and not any(host == d or host.endswith("." + d) for d in allowed):
            raise NetworkRefused(f"{host} is not in the owner's allowed domains")
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return parts.scheme, host, port, path

    def _check_outbound_data(self, url: str, purpose: str) -> None:
        """The URL leaves the machine: secrets and sensitive data in it are refused (Egress Guard)."""
        if default_redactor.redact(url) != url:
            raise NetworkRefused("the URL contains something shaped like a credential or a registered secret")
        try:
            EgressGuard(self.conn).check(provider="web", classification=classify_text(url), purpose=purpose)
        except EgressBlocked:
            raise NetworkRefused("the URL carries sensitive personal data; it is not sent to a website") from None

    def _resolve(self, host: str, port: int) -> str:
        try:
            ipaddress.ip_address(host)
            candidates = [host]
        except ValueError:
            try:
                infos = self.resolver(host, port, proto=socket.IPPROTO_TCP)
            except (OSError, UnicodeError):
                raise NetworkRefused(f"could not resolve {host}") from None
            candidates = [str(i[4][0]) for i in infos]
        if not candidates:
            raise NetworkRefused(f"could not resolve {host}")
        for ip in candidates:  # every address must be public, or none is used (rebinding/split answers)
            problem = address_problem(ip)
            if problem and not (test_mode() and ipaddress.ip_address(ip).is_loopback and host in ("127.0.0.1", "::1")):
                raise NetworkRefused(f"{host} resolves to a {problem}; refused")
        return candidates[0]

    # ------------------------------------------------------------------ receipts

    def _receipt(self, *, task_id: str | None, url: str, decision: str, reason: str, status: int | None = None,
                 ip: str | None = None, nbytes: int = 0, sha256: str | None = None, purpose: str) -> str:
        rid = new_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO network_requests(id, task_id, purpose, url, resolved_ip, decision, reason, status,"
                " bytes, sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rid, task_id, purpose, default_redactor.redact(url)[:2000], ip, decision, reason[:500], status,
                 nbytes, sha256, to_utc_str(self.clock.now())),
            )
        return rid

    # ------------------------------------------------------------------ fetch

    def fetch(self, url: str, *, task_id: str | None, purpose: str = "web") -> FetchResult:
        receipts: list[str] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                if not self.enabled():
                    raise NetworkRefused("web research is disabled; the owner can enable it in Settings")
                scheme, host, port, path = self._check_url(current)
                self._check_outbound_data(current, purpose)
                ip = self._resolve(host, port)
            except NetworkRefused as exc:
                receipts.append(self._receipt(task_id=task_id, url=current, decision="REFUSED", reason=exc.reason,
                                              purpose=purpose))
                raise
            conn_cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
            conn = conn_cls(host, ip, port, TIMEOUT_S)
            try:
                conn.request("GET", path, headers={"User-Agent": "Atlas/1 (+research; owner-authorized)",
                                                   "Accept": "text/html,text/plain,application/json;q=0.9"})
                resp = conn.getresponse()
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.getheader("Location") or ""
                    receipts.append(self._receipt(task_id=task_id, url=current, decision="REDIRECT",
                                                  reason=f"-> {location[:300]}", status=resp.status, ip=ip,
                                                  purpose=purpose))
                    if not location:
                        raise NetworkRefused("redirect without a location")
                    current = urljoin(current, location)
                    continue  # the next hop goes through every check again
                ctype = (resp.getheader("Content-Type") or "").lower()
                if not ctype.startswith(TEXT_TYPES):
                    raise NetworkRefused(f"content type {ctype or '(none)'} is not text; not downloaded")
                body = resp.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise NetworkRefused(f"response larger than {MAX_BYTES} bytes")
            except NetworkRefused as exc:
                receipts.append(self._receipt(task_id=task_id, url=current, decision="REFUSED", reason=exc.reason,
                                              ip=ip, purpose=purpose))
                raise
            except (OSError, http.client.HTTPException) as exc:
                receipts.append(self._receipt(task_id=task_id, url=current, decision="FAILED",
                                              reason=type(exc).__name__, ip=ip, purpose=purpose))
                raise AtlasError(ErrorCode.PROVIDER_UNAVAILABLE, f"could not fetch {host}: {type(exc).__name__}",
                                 persisted="nothing retrieved") from None
            finally:
                conn.close()
            digest = hashlib.sha256(body).hexdigest()
            receipts.append(self._receipt(task_id=task_id, url=current, decision="ALLOWED", reason="ok",
                                          status=resp.status, ip=ip, nbytes=len(body), sha256=digest,
                                          purpose=purpose))
            return FetchResult(url, current, resp.status, ctype, body, digest, receipts)
        self._receipt(task_id=task_id, url=current, decision="REFUSED", reason="too many redirects", purpose=purpose)
        raise NetworkRefused("too many redirects")
