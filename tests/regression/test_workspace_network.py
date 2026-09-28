"""Public-browser egress tested with a local HTTP server; no Internet or paid services."""
from __future__ import annotations

import base64
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from security.network.browser import BrowserNetwork
from security.network.mediator import NetworkMediator
from tests.conftest import World


@contextmanager
def site():
    received: list[dict[str, Any]] = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append({"path": self.path, "headers": dict(self.headers)})
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                self.end_headers()
                return
            if self.path == "/cookie":
                self.send_response(200)
                self.send_header("Set-Cookie", "private_session=sentinel; HttpOnly")
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<p>Public page</p>")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream" if self.path == "/binary" else "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>public response</h1>")
        def log_message(self, *_):
            return
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def enable(world: World) -> None:
    world.conn.execute("INSERT INTO settings(revision,config_json,updated_at,updated_by) VALUES (?,?,?,?)",
                       (1, json.dumps({"research": {"web_enabled": True}}), "2026-01-01T00:00:00.000Z", "synthetic-owner"))


def request(url: str) -> dict[str, Any]:
    return {"url": url, "method": "GET", "resource_type": "Document", "has_body": False}


def bridge(world: World, *, level: str = "INTERNAL", allowed=lambda: True) -> BrowserNetwork:
    return BrowserNetwork(NetworkMediator(world.conn, world.clock), task_id=None, classification=level, authorized=allowed)


def test_research_is_off_until_owner_enables(world: World) -> None:
    with site() as (url, received):
        assert bridge(world)(request(url))["allowed"] is False
        assert received == []


def test_public_page_retrieval_and_scoped_receipt(world: World) -> None:
    enable(world)
    network = bridge(world)
    with site() as (url, received):
        response = network(request(url))
        assert response["allowed"] is True and base64.b64decode(response["body"]) == b"<h1>public response</h1>"
        assert len(received) == 1 and url in network.documents
        assert world.conn.execute("SELECT decision FROM network_requests WHERE id=?", (response["receipt"],)).fetchone()[0] == "ALLOWED"


@pytest.mark.parametrize("changes", [{"method": "POST"}, {"has_body": True}, {"headers": {"Authorization": "never-sent"}}, {"cookies": "never-sent"}])
def test_guest_cannot_add_credentials_or_mutating_payload(world: World, changes: dict) -> None:
    enable(world)
    with site() as (url, received):
        r = request(url)
        r.update(changes)
        assert bridge(world)(r)["allowed"] is False
        assert received == []


@pytest.mark.parametrize("level", ["SENSITIVE", "SECRET"])
def test_sensitive_task_does_not_leak_via_url_callbacks(world: World, level: str) -> None:
    enable(world)
    with site() as (url, received):
        assert bridge(world, level=level)(request(url))["allowed"] is False
        assert received == []


def test_owner_revoke_interrupts_network_release(world: World) -> None:
    enable(world)
    with site() as (url, received):
        assert bridge(world, allowed=lambda: False)(request(url))["allowed"] is False
        assert received == []


def test_response_cookies_are_not_imported_into_public_browser(world: World) -> None:
    enable(world)
    with site() as (url, received):
        response = bridge(world)(request(url + "/cookie"))
        assert response["allowed"] is True
        assert all(h["name"].lower() != "set-cookie" for h in response["headers"])
        assert "Cookie" not in received[0]["headers"] and "Authorization" not in received[0]["headers"]


def test_redirect_to_cloud_metadata_denied_before_following(world: World) -> None:
    enable(world)
    with site() as (url, received):
        assert bridge(world)(request(url + "/redirect"))["allowed"] is False
        assert [x["path"] for x in received] == ["/redirect"]


def test_binary_download_is_not_fulfilled(world: World) -> None:
    enable(world)
    with site() as (url, _):
        assert bridge(world)(request(url + "/binary"))["allowed"] is False


def test_callback_budget_is_hard_bounded(world: World) -> None:
    enable(world)
    network = bridge(world)
    network.calls = 80
    with site() as (url, received):
        assert network(request(url))["allowed"] is False
        assert received == []


def test_dns_answers_all_must_be_public_and_no_request_on_private(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    enable(world)
    monkeypatch.delenv("ATLAS_ALLOW_TEST_ENDPOINTS", raising=False)
    def resolver(*_args, **_kwargs):
        return [(None, None, None, None, ("93.184.216.34", 443)), (None, None, None, None, ("192.168.1.2", 443))]
    network = BrowserNetwork(NetworkMediator(world.conn, world.clock, resolver=resolver), task_id=None,
                             classification="INTERNAL", authorized=lambda: True)
    assert network(request("https://example.test"))["allowed"] is False
    assert network.documents == {}
