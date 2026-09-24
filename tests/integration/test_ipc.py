"""Etapa 3 / spec 13.4-13.5 / review R-05: authenticated IPC over real sockets.

Identity comes from the session token, never from the body. Conversation reflects real events:
messages are persisted first, "pare" changes state, and replies only reference tasks that exist.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from core.ipc.server import PROTOCOL, UnixSocketServer, serve_connection
from core.ipc.sessions import SessionRegistry
from core.service import CoreService
from runtime.tools.registry import ToolRegistry
from security.broker.broker import Broker
from security.budget.budget import BudgetLimits, BudgetManager
from security.policy.engine import PolicyEngine
from shared.actors import Actor
from shared.contracts import errors_for
from shared.framing import MAX_FRAME, recv_frame, send_frame
from shared.ids import new_id
from storage.store import open_store
from tests.conftest import World


def factory(world: World):  # type: ignore[no-untyped-def]
    def make() -> CoreService:
        conn = open_store(world.path, world.clock)  # each connection thread gets its own DB connection
        broker = Broker(
            conn,
            world.clock,
            registry=ToolRegistry(conn, world.clock),
            policy=PolicyEngine(),
            budget=BudgetManager(conn, world.clock, BudgetLimits("USD", None, None)),
        )
        return CoreService(conn, world.clock, broker)

    return make


class Client:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.n = 0

    def hello(self, token: str, protocol: str = PROTOCOL) -> dict[str, Any]:
        send_frame(self.sock, {"hello": token, "protocol": protocol})
        return recv_frame(self.sock)

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.n += 1
        params.setdefault("schema_version", "1.0")
        params.setdefault("correlation_id", f"corr-{self.n:06d}")
        send_frame(
            self.sock, {"jsonrpc": "2.0", "id": f"req-{self.n:06d}", "method": method, "params": params}
        )
        resp = recv_frame(self.sock)
        assert errors_for("ipc_response", resp) == [], resp  # every reply honours the contract
        return resp


@pytest.fixture
def sessions() -> SessionRegistry:
    return SessionRegistry()


@pytest.fixture
def connect(world: World, sessions: SessionRegistry) -> Iterator[Any]:
    opened: list[socket.socket] = []

    def _connect(actor: Actor | None = None, employee_id: str | None = None) -> Client:
        a, b = socket.socketpair()
        opened.append(a)
        threading.Thread(target=serve_connection, args=(b, sessions, factory(world)), daemon=True).start()
        client = Client(a)
        if actor is not None:
            token = sessions.issue(actor, employee_id or world.employee.id)
            assert client.hello(token)["hello"] == "ok"
        return client

    yield _connect
    for s in opened:
        s.close()


def err(resp: dict[str, Any]) -> str:
    return str(resp["error"]["data"]["atlas_code"])


def test_handshake_rejects_unknown_token_and_wrong_protocol(
    connect: Any, sessions: SessionRegistry, world: World
) -> None:
    assert connect().hello("forged-token")["hello"] == "rejected"
    token = sessions.issue(world.owner, world.employee.id)
    assert connect().hello(token, protocol="0.9")["hello"] == "rejected"


def test_oversized_frame_closes_connection(connect: Any, world: World) -> None:
    c = connect(world.owner)
    c.sock.sendall(struct.pack(">I", MAX_FRAME + 1))
    with pytest.raises((EOFError, ConnectionError, OSError)):
        recv_frame(c.sock)


def test_body_cannot_declare_actor(connect: Any, world: World) -> None:
    c = connect(Actor("runtime", "rt", "internal"))
    r = c.call(
        "tasks.create",
        employee_id=world.employee.id,
        objective="x",
        artifact_ids=[],
        constraints={"external_writes": False, "purchases": False},
        actor="owner",
    )
    assert err(r) == "INVALID_INPUT"


def test_runtime_session_cannot_act_as_owner(connect: Any, world: World) -> None:
    c = connect(Actor("runtime", "rt", "internal"))
    r = c.call(
        "approvals.decide", approval_id=new_id(), decision="APPROVE", params_hash="a" * 64, nonce="b" * 32
    )
    assert err(r) == "UNAUTHORIZED"
    r = c.call(
        "tasks.create",
        employee_id=world.employee.id,
        objective="x",
        artifact_ids=[],
        constraints={"external_writes": False, "purchases": False},
    )
    assert err(r) == "UNAUTHORIZED"


def test_session_is_bound_to_its_employee(connect: Any, world: World) -> None:
    c = connect(world.owner)
    r = c.call("tasks.list", employee_id=new_id())
    assert err(r) == "UNAUTHORIZED"


def test_task_lifecycle_over_ipc(connect: Any, world: World) -> None:
    c = connect(world.owner)
    created = c.call(
        "tasks.create",
        employee_id=world.employee.id,
        objective="Comparar propostas sinteticas",
        artifact_ids=[],
        constraints={"external_writes": False, "purchases": False},
    )
    task = created["result"]["task"]
    assert task["state"] == "CREATED"  # persisted before anything claims it started
    got = c.call("tasks.get", task_id=task["task_id"])["result"]["task"]
    paused = c.call("tasks.pause", task_id=task["task_id"], expected_version=got["version"])["result"]["task"]
    assert paused["state"] == "PAUSED"
    resumed = c.call("tasks.resume", task_id=task["task_id"], expected_version=paused["version"])["result"]
    assert resumed["task"]["state"] == "CREATED"
    stale = c.call("tasks.cancel", task_id=task["task_id"], expected_version=1)
    assert err(stale) == "VERSION_CONFLICT"
    listed = c.call("tasks.list", employee_id=world.employee.id)["result"]["tasks"]
    assert [t["task_id"] for t in listed] == [task["task_id"]]


def test_conversation_persists_dedups_and_stop_changes_state(connect: Any, world: World) -> None:
    from runtime.tasks.engine import TaskEngine
    from runtime.tasks.state_machine import TaskState

    engine = TaskEngine(world.conn, world.clock)
    tid = engine.create(world.owner, employee_id=world.employee.id, objective="tarefa longa")
    for to in (TaskState.UNDERSTANDING, TaskState.PLANNING, TaskState.READY):
        engine.transition(tid, to, expected_version=engine.get(tid)["version"], actor=world.owner, reason="t")
    engine.acquire_lease(tid, "w1")
    c = connect(world.owner)
    conv, msg = new_id(), new_id()
    first = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=conv,
        client_message_id=msg,
        text="Como esta a tarefa?",
    )["result"]
    again = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=conv,
        client_message_id=msg,
        text="Como esta a tarefa?",
    )["result"]
    assert again["duplicate"] is True and again["message_id"] == first["message_id"]
    assert first["task_id"] is None and first["control"] is None  # no invented work
    stop = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=conv,
        client_message_id=new_id(),
        text="Pare!",
    )["result"]
    assert stop["control"] == "stopped" and stop["paused_tasks"] == [tid]
    assert engine.get(tid)["state"] == "PAUSED"
    roles = [r[0] for r in world.conn.execute("SELECT role FROM messages ORDER BY rowid")]
    assert roles == ["owner", "employee", "owner", "employee"]  # each owner message answered exactly once
    assert first["intent"] == "status" and "tarefa longa" in first["reply"]["content"]
    assert again["reply"]["message_id"] == first["reply"]["message_id"]  # resend repeats nothing
    assert "pausada" in stop["reply"]["content"]


def test_paired_device_can_talk_but_not_cancel(connect: Any, world: World) -> None:
    c = connect(Actor("device", "phone-1", "paired_device"))
    ok = c.call(
        "conversations.send",
        employee_id=world.employee.id,
        conversation_id=new_id(),
        client_message_id=new_id(),
        text="Resumo do dia, por favor",
    )
    assert "result" in ok
    r = c.call("tasks.cancel", task_id=new_id(), expected_version=1)
    assert err(r) == "UNAUTHORIZED"


def test_events_can_be_resumed_by_sequence(connect: Any, world: World) -> None:
    c = connect(world.owner)
    c.call(
        "tasks.create",
        employee_id=world.employee.id,
        objective="x",
        artifact_ids=[],
        constraints={"external_writes": False, "purchases": False},
    )
    first = c.call("events.subscribe", employee_id=world.employee.id, after_sequence_id=0)["result"]
    assert first["events"]
    later = c.call(
        "events.subscribe", employee_id=world.employee.id, after_sequence_id=first["last_sequence_id"]
    )["result"]
    assert later["events"] == []


def test_missing_components_answer_honestly(connect: Any, world: World) -> None:
    c = connect(world.owner)
    assert err(c.call("workspace.observe", employee_id=world.employee.id)) == "WORKSPACE_OFFLINE"
    r = c.call("artifacts.import", employee_id=world.employee.id, upload_ref=new_id(), declared_name="a.txt")
    assert err(r) == "INVALID_INPUT" and "not available" in r["error"]["message"]
    health = c.call("system.health")["result"]
    assert health["components"]["workspace"] == "not_available"


def test_settings_cannot_widen_security_over_ipc(connect: Any, world: World) -> None:
    import yaml

    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "atlas.default.yaml").read_text())
    c = connect(world.owner)
    assert c.call("settings.update", expected_revision=0, settings=cfg)["result"]["revision"] == 1
    cfg["security"]["host_shell_enabled"] = True
    assert err(c.call("settings.update", expected_revision=1, settings=cfg)) == "INVALID_INPUT"
    runtime = connect(Actor("runtime", "rt", "internal"))
    cfg["security"]["host_shell_enabled"] = False
    assert err(runtime.call("settings.update", expected_revision=1, settings=cfg)) == "UNAUTHORIZED"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix domain socket server is POSIX-only (runs in CI)")
def test_unix_socket_server_in_private_directory(
    world: World, sessions: SessionRegistry, tmp_path: Path
) -> None:
    import shutil
    import tempfile

    with pytest.raises(OSError, match="OS limit"):
        UnixSocketServer(tmp_path / ("x" * 120), sessions, factory(world))
    short = Path(tempfile.mkdtemp(prefix="atl", dir="/tmp"))
    server = UnixSocketServer(short / "ipc", sessions, factory(world))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert oct((short / "ipc").stat().st_mode & 0o777) == "0o700"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(server.path))
        client = Client(s)
        assert client.hello(sessions.issue(world.owner, world.employee.id))["hello"] == "ok"
        assert client.call("system.health")["result"]["status"] == "ok"
        s.close()
    finally:
        server.close()
        shutil.rmtree(short, ignore_errors=True)
