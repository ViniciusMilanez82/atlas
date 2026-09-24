"""End-to-end: the real atlas-core daemon as a separate process (POSIX; runs on the CI runners).

Linux and macOS: the daemon starts, bootstraps identity, issues a 0600 session file, answers IPC,
keeps tasks queued with an explicit reason while intelligence is not configured, and shuts down on
SIGTERM.

macOS with the Keychain service built (ATLAS_KEYCHAIN_AGENT): the owner registers an API key into the
REAL Keychain through IPC, saves budget ceilings, runs 'Testar inteligência' against a LOCAL FAKE
model server, and the worker completes a delegated task with a verified deliverable; after a restart
the task and identity are still there. The model server is a clearly labeled fake: this proves the
wiring, not model quality, and no real provider is contacted.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.integration.test_ipc import Client

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="atlas-core needs Unix domain sockets")
ROOT = Path(__file__).resolve().parents[2]


class FakeModelServer:
    """FAKE OpenAI-compatible endpoint for the daemon. Answers the intelligence check and plays a
    two-step agent: write a report, then finish with the artifact id it sees in the context."""

    def __init__(self) -> None:
        outer = self
        self.calls = 0

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                return

            def _json(self, status: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("x-request-id", f"fake-{outer.calls}")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._json(200, {"id": self.path.rsplit("/", 1)[-1], "object": "model"})

            def do_POST(self) -> None:
                outer.calls += 1
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                props = body.get("text", {}).get("format", {}).get("schema", {}).get("properties", {})
                prompt = chr(10).join(str(m.get("content", "")) for m in body.get("input", []))
                if "ok" in props:
                    text = json.dumps({"ok": True, "word": "atlas"})
                else:
                    import re

                    written = re.findall(r'"artifact_id": "([0-9a-f-]{36})", "name": "relatorio.md"', prompt)
                    if written:
                        text = json.dumps(
                            {
                                "decision": "finish",
                                "summary": "entregar",
                                "tool_id": "",
                                "input_json": "{}",
                                "artifact_id": written[-1],
                                "question": "",
                            }
                        )
                    else:
                        report = (
                            "# Relatorio sintetico\\n\\n"
                            + "Conteudo verificavel sobre a tarefa delegada. " * 8
                        )
                        text = json.dumps(
                            {
                                "decision": "tool",
                                "summary": "escrever relatorio",
                                "tool_id": "artifact.write_text",
                                "input_json": json.dumps({"name": "relatorio.md", "content": report}),
                                "artifact_id": "",
                                "question": "",
                            }
                        )
                self._json(
                    200,
                    {
                        "id": f"resp_{outer.calls}",
                        "model": body["model"],
                        "status": "completed",
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
                        "usage": {
                            "input_tokens": 400,
                            "input_tokens_details": {"cached_tokens": 0},
                            "output_tokens": 80,
                        },
                    },
                )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Daemon:
    def __init__(self, data: Path, ipc: Path, base_url: str, env: dict[str, str]) -> None:
        self.ipc = ipc
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "core",
                "--data-dir",
                str(data),
                "--ipc-dir",
                str(ipc),
                "--openai-base-url",
                base_url,
                "--worker-interval",
                "0.2",
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT), **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        line = self.proc.stdout.readline() if self.proc.stdout else ""
        assert '"ready"' in line, (line, self.proc.stderr.read() if self.proc.stderr else "")
        session = json.loads((ipc / "session.json").read_text(encoding="utf-8"))
        assert oct((ipc / "session.json").stat().st_mode & 0o777) == "0o600"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(session["socket"])
        self.client = Client(s)
        assert self.client.hello(session["owner_token"])["hello"] == "ok"
        self.employee_id = session["employee_id"]

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        return self.client.call(method, **params)

    def stop(self) -> None:
        self.client.sock.close()
        self.proc.send_signal(signal.SIGTERM)
        assert self.proc.wait(10) == 0


@pytest.fixture
def dirs() -> Iterator[tuple[Path, Path]]:
    base = Path(tempfile.mkdtemp(prefix="atd", dir="/tmp"))
    yield base / "data", base / "ipc"
    shutil.rmtree(base, ignore_errors=True)


def wait_for(fn: Any, timeout: float = 30.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("condition not reached")


def test_daemon_lifecycle_without_intelligence(dirs: tuple[Path, Path]) -> None:
    data, ipc = dirs
    d = Daemon(data, ipc, "http://127.0.0.1:9/v1", {})
    try:
        ident = d.call("identity.get")["result"]
        assert ident["name"] == "Atlas" and ident["timezone"] == "America/Sao_Paulo"
        health = d.call("system.health")["result"]
        assert health["components"]["intelligence"] == "not_configured"
        assert health["components"]["worker"] == "ok" and health["status"] == "ok"  # real daemon has a live worker
        assert health["intelligence_reason"]  # the reason is explicit, never a fake reply
        task = d.call(
            "tasks.create",
            employee_id=d.employee_id,
            objective="Resumo sintetico",
            artifact_ids=[],
            constraints={"external_writes": False, "purchases": False},
        )["result"]["task"]
        time.sleep(1.0)
        assert d.call("tasks.get", task_id=task["task_id"])["result"]["task"]["state"] == "CREATED"
    finally:
        d.stop()
    assert not (ipc / "session.json").exists()


@pytest.mark.macos
def test_alpha_flow_with_real_keychain_and_fake_model(dirs: tuple[Path, Path]) -> None:
    agent = os.environ.get("ATLAS_KEYCHAIN_AGENT")
    if not agent or not Path(agent).is_file():
        pytest.skip("NAO EXECUTADO: build platform/macos/AtlasKit and set ATLAS_KEYCHAIN_AGENT")
    data, ipc = dirs
    kc_dir = Path(tempfile.mkdtemp(prefix="akc", dir="/tmp"))
    os.chmod(kc_dir, 0o700)
    token_file = kc_dir / "token"
    token_file.write_text(uuid.uuid4().hex, encoding="utf-8")
    os.chmod(token_file, 0o600)
    sock = kc_dir / "kc.sock"
    kc = subprocess.Popen([agent, str(sock), str(token_file), f"com.atlas.tests.e2e.{uuid.uuid4().hex}"])
    fake = FakeModelServer()
    env = {"ATLAS_KEYCHAIN_SOCKET": str(sock), "ATLAS_KEYCHAIN_TOKEN_FILE": str(token_file)}
    try:
        wait_for(sock.exists, 5)
        d = Daemon(data, ipc, fake.url, env)
        synthetic_key = "synthetic-test-key-" + uuid.uuid4().hex  # atlas-scan: allow-fake-secret
        ref = d.call(
            "credentials.register",
            provider="openai",
            secret_b64=base64.b64encode(synthetic_key.encode()).decode(),
        )
        assert "credential_ref" in ref["result"] and synthetic_key not in json.dumps(ref)
        cfg = yaml.safe_load((ROOT / "config" / "atlas.default.yaml").read_text(encoding="utf-8"))
        cfg["budget"]["monthly_limit_minor"] = 500
        cfg["budget"]["per_task_limit_minor"] = 200
        cfg["budget"]["accept_reference_prices"] = True  # owner accepts the unverified table as an estimate
        assert d.call("settings.update", expected_revision=0, settings=cfg)["result"]["revision"] == 1
        report = d.call("intelligence.check", model_id="gpt-6-sol", max_cost_minor=5)["result"]["report"]
        assert report["passed"] is True, report
        assert d.call("system.health")["result"]["components"]["intelligence"] == "ready"
        task = d.call(
            "tasks.create",
            employee_id=d.employee_id,
            objective="Escreva um relatorio curto sobre a tarefa",
            artifact_ids=[],
            constraints={"external_writes": False, "purchases": False},
        )["result"]["task"]
        done = wait_for(
            lambda: (
                (t := d.call("tasks.get", task_id=task["task_id"])["result"]["task"])["state"]
                in ("COMPLETED", "BLOCKED", "FAILED")
                and t
            )
        )
        assert done["state"] == "COMPLETED", done
        arts = d.call("artifacts.list", task_id=task["task_id"])["result"]["artifacts"]
        assert [a["name"] for a in arts if a["relation"] == "output"] == ["relatorio.md"]
        d.stop()
        d2 = Daemon(data, ipc, fake.url, env)  # restart: state persisted, nothing re-run
        calls_before = fake.calls
        assert d2.call("tasks.get", task_id=task["task_id"])["result"]["task"]["state"] == "COMPLETED"
        time.sleep(1.0)
        assert fake.calls == calls_before
        d2.stop()
    finally:
        fake.close()
        kc.terminate()
        kc.wait(5)
        shutil.rmtree(kc_dir, ignore_errors=True)
