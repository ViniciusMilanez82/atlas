"""N14 (mediation part) and N16 (web.fetch, sources recuperadas): every web request goes through the
mediator - public addresses only (pinned after one resolution), redirects re-checked hop by hop,
sensitive data and credentials never leave in the URL, size/type limits, owner switch and domain
lists, and a receipt for every attempt. A local HTTP server stands in for the Internet (test mode
accepts only the literal loopback address); no real network is used.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from runtime.verification.verifier import DeliverableSpec
from security.network import mediator as med
from security.network.mediator import NetworkMediator, NetworkRefused, address_problem
from tests.integration.test_alpha2 import base_config
from tests.regression.r5_harness import R5World, decision

PAGE = (
    "<html><head><title>Tabela de preços</title><script>var tracking = 'x';</script></head><body>"
    "<h1>Módulos solares</h1><p>O módulo solar custa R$ 1.250,00.</p><table><tr><td>Garantia</td>"
    "<td>12 anos</td></tr></table></body></html>"
)


class _Site:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.hits: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                return

            def do_GET(self) -> None:
                outer.hits.append(self.path)
                status, headers, body = outer.routes.get(self.path, (404, {"Content-Type": "text/plain"}, b"nf"))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def site() -> Iterator[_Site]:
    s = _Site()
    s.routes["/precos"] = (200, {"Content-Type": "text/html; charset=utf-8"}, PAGE.encode("utf-8"))
    yield s
    s.close()


def _enable(r5: R5World, **research: Any) -> None:
    cfg = base_config()
    cfg["research"] = {"web_enabled": True, **research}
    with r5.conn:
        rev = r5.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM settings").fetchone()[0]
        r5.conn.execute(
            "INSERT INTO settings(revision, config_json, updated_at, updated_by) VALUES (?,?,?,?)",
            (rev + 1, json.dumps(cfg), "2026-01-01T00:00:00.000Z", "owner:test"),
        )


def _receipts(r5: R5World) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in r5.conn.execute("SELECT decision, reason FROM network_requests ORDER BY rowid")]


def _fake_dns(mapping: dict[str, list[str]]) -> Any:
    def resolve(host: str, port: int, proto: int = 0) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (ip, port)) for ip in mapping[host]]

    return resolve


def test_disabled_by_default_and_every_attempt_has_a_receipt(r5: R5World, site: _Site) -> None:
    with pytest.raises(NetworkRefused, match="disabled"):
        NetworkMediator(r5.conn, r5.clock).fetch(site.base + "/precos", task_id=None)
    assert _receipts(r5)[0][0] == "REFUSED" and not site.hits  # nothing left the machine


def test_the_agent_fetches_a_page_and_it_becomes_a_citable_source(r5: R5World, site: _Site) -> None:
    """R5-08 'recuperação real controlada': real HTTP through the mediator, then the verifier."""
    _enable(r5)
    tid = r5.create("Relatório de teste sobre fornecedores de módulos.")
    url = site.base + "/precos"
    r5.provider.reply = decision("tool", tool_id="web.fetch", input_json=json.dumps({"url": url}))
    calls = {"n": 0}

    def step(_: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            return decision("tool", tool_id="web.fetch", input_json=json.dumps({"url": url}))
        return decision("ask_owner", question="Quer o relatório em PDF?")

    r5.provider.reply = step
    r5.runner.run(tid, DeliverableSpec())
    obs = r5.conn.execute("SELECT content, classification FROM step_observations WHERE task_id = ?", (tid,)).fetchone()
    out = json.loads(obs[0])
    assert "R$ 1.250,00" in out["text"] and "tracking" not in out["text"]  # scripts dropped
    assert out["final_url"] == url and obs[1] == "PUBLIC"
    assert site.hits == ["/precos"]
    assert ("ALLOWED", "ok") in _receipts(r5)
    backed = f"O módulo solar custa R$ 1.250,00 e a garantia é de 12 anos. Fonte: {url}"
    assert r5.verifier._sources(tid, backed, 1, DeliverableSpec()) is None
    wrong = f"O módulo solar custa R$ 990,00. Fonte: {url}"
    assert "não sustenta" in (r5.verifier._sources(tid, wrong, 1, DeliverableSpec()) or "")


@pytest.mark.parametrize(
    "ips,why",
    [
        (["10.0.0.5"], "private"),
        (["169.254.169.254"], "link-local"),
        (["127.0.0.1"], "loopback"),
        (["100.64.1.1"], "carrier-grade"),
        (["93.184.216.34", "192.168.1.10"], "private"),  # one bad answer poisons the resolution
    ],
)
def test_internal_addresses_are_refused_even_behind_a_public_name(r5: R5World, ips: list[str], why: str) -> None:
    _enable(r5)
    m = NetworkMediator(r5.conn, r5.clock, resolver=_fake_dns({"precos.example.test": ips}))
    with pytest.raises(NetworkRefused, match=why):
        m.fetch("https://precos.example.test/tabela", task_id=None)


def test_redirect_to_an_internal_address_is_refused_at_the_hop(r5: R5World, site: _Site) -> None:
    _enable(r5)
    site.routes["/salto"] = (302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b"")
    with pytest.raises(NetworkRefused, match=r"link-local|port|only"):
        NetworkMediator(r5.conn, r5.clock).fetch(site.base + "/salto", task_id=None)
    decisions = [d for d, _ in _receipts(r5)]
    assert decisions == ["REDIRECT", "REFUSED"]


def test_redirect_on_the_same_site_is_followed_after_rechecking(r5: R5World, site: _Site) -> None:
    _enable(r5)
    site.routes["/antigo"] = (301, {"Location": "/precos"}, b"")
    page = NetworkMediator(r5.conn, r5.clock).fetch(site.base + "/antigo", task_id=None)
    assert page.final_url.endswith("/precos") and page.status == 200


@pytest.mark.parametrize(
    "url,why",
    [
        ("https://busca.example.test/?q=diagnostico+medico+SENTINELA_URL_4411", "sensitive"),
        ("https://api.example.test/?api_key=" + "sk-" + "proj-" + "ABCDEFGHIJKLMNOPQRSTUV123", "credential"),
        ("ftp://arquivos.example.test/lista", "only http"),
        ("https://user:pw@example.test/", "user information"),
        ("https://example.test:8443/", "port"),
    ],
)
def test_outbound_data_and_shape_rules(r5: R5World, url: str, why: str) -> None:
    _enable(r5)
    m = NetworkMediator(r5.conn, r5.clock, resolver=_fake_dns({"busca.example.test": ["93.184.216.34"],
                                                                "api.example.test": ["93.184.216.34"]}))
    with pytest.raises(NetworkRefused, match=why):
        m.fetch(url, task_id=None)
    assert _receipts(r5)[-1][0] == "REFUSED"  # refused before any connection, with a receipt


def test_owner_domain_lists(r5: R5World) -> None:
    _enable(r5, allowed_domains=["gov.br"], blocked_domains=["ruim.gov.br"])
    m = NetworkMediator(r5.conn, r5.clock, resolver=_fake_dns({}))
    with pytest.raises(NetworkRefused, match="allowed domains"):
        m.fetch("https://example.com/", task_id=None)
    with pytest.raises(NetworkRefused, match="blocked"):
        m.fetch("https://www.ruim.gov.br/", task_id=None)


def test_type_and_size_limits(r5: R5World, site: _Site, monkeypatch: Any) -> None:
    _enable(r5)
    site.routes["/binario"] = (200, {"Content-Type": "application/octet-stream"}, b"\x00" * 10)
    with pytest.raises(NetworkRefused, match="not text"):
        NetworkMediator(r5.conn, r5.clock).fetch(site.base + "/binario", task_id=None)
    site.routes["/grande"] = (200, {"Content-Type": "text/plain"}, b"a" * 2048)
    monkeypatch.setattr(med, "MAX_BYTES", 1024)
    with pytest.raises(NetworkRefused, match="larger"):
        NetworkMediator(r5.conn, r5.clock).fetch(site.base + "/grande", task_id=None)


def test_address_classifier() -> None:
    assert address_problem("8.8.8.8") is None
    for ip in ("::1", "fe80::1", "fd00::1", "::ffff:10.0.0.1", "0.0.0.0", "224.0.0.1"):
        assert address_problem(ip) is not None, ip
