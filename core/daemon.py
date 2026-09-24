"""atlas-core daemon (ADR-012/013): the only process that writes the database.

Started by the Supervisor. On start it migrates the database, creates the identity on first run,
recovers interrupted work (spec 12.4), issues the owner's local-app session token into a 0600 file,
serves the IPC socket, and runs one worker that executes tasks only when intelligence is configured
(credential in the Keychain, budget ceilings, validated model). Without intelligence, tasks stay
queued and health says exactly why - nothing is simulated.

    python -m core --data-dir DIR --ipc-dir DIR [--employee-name Atlas] [--openai-base-url URL]
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path
from types import FrameType

from core.conversation import ConversationService
from core.health import WorkerMonitor
from core.intelligence import IntelligenceSetup
from core.ipc.server import UnixSocketServer
from core.ipc.sessions import SessionRegistry
from core.service import CoreService
from runtime.agent.loop import AgentRunner, RunOutcome
from runtime.artifacts.manager import ArtifactManager
from runtime.memory.manager import MemoryManager
from runtime.models.openai_responses import DEFAULT_BASE_URL
from runtime.tasks.engine import TaskEngine
from runtime.tasks.limits import ProgressGuard
from runtime.tasks.scheduler import Scheduler
from runtime.tasks.watchdog import Watchdog
from runtime.tools.builtin import BUILTIN_MANIFESTS, BuiltinTools
from runtime.tools.registry import ToolRegistry
from runtime.verification.verifier import DeliverableSpec, Verifier
from security.broker.broker import Broker
from security.budget.budget import BudgetManager
from security.policy.engine import PolicyEngine
from security.vault.vault import Vault, VaultBackend, VaultUnavailable, platform_backend
from shared.actors import Actor
from shared.clock import Clock, SystemClock
from shared.errors import AtlasError
from storage import journal
from storage.db import transaction
from storage.repositories.identity import create_employee, create_owner
from storage.store import open_store

SUPERVISOR = Actor("supervisor", "atlas-supervisor", "internal")


class Core:
    def __init__(self, data_dir: Path, ipc_dir: Path, base_url: str, clock: Clock | None = None) -> None:
        self.data_dir = data_dir
        self.ipc_dir = ipc_dir
        self.base_url = base_url
        self.clock = clock or SystemClock()
        self.db_path = data_dir / "atlas.sqlite"
        self.store_root = data_dir / "artifacts"
        self.stop = threading.Event()
        self.monitor = WorkerMonitor(self.clock)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.vault_backend: VaultBackend | None
        try:
            self.vault_backend = platform_backend()
            self.vault_reason = "ok"
        except VaultUnavailable as exc:
            self.vault_backend = None
            self.vault_reason = str(exc)

    # ---------------------------------------------------------------- wiring (one set per connection/thread)

    def _components(self) -> tuple[object, Broker, IntelligenceSetup, ArtifactManager]:
        conn = open_store(self.db_path, self.clock)
        registry = ToolRegistry(conn, self.clock)
        BuiltinTools(self.db_path, self.store_root, self.clock).register(registry, enabled_by=SUPERVISOR)
        vault = Vault(conn, self.vault_backend, self.clock) if self.vault_backend else None
        intel = IntelligenceSetup(conn, self.clock, vault, self.base_url)
        broker = Broker(
            conn,
            self.clock,
            registry=registry,
            policy=PolicyEngine(),
            budget=BudgetManager.live(conn, self.clock),  # current revision in every reservation (A3-19)
            vault=vault,
        )
        return conn, broker, intel, ArtifactManager(conn, self.clock, self.store_root)

    def service(self) -> CoreService:
        _, broker, intel, artifacts = self._components()
        return CoreService(
            broker.conn, self.clock, broker, intelligence=intel, artifacts=artifacts, worker=self.monitor
        )

    # ---------------------------------------------------------------- lifecycle

    def bootstrap(self, owner_name: str, employee_name: str, locale: str, timezone: str) -> tuple[str, str]:
        conn = open_store(self.db_path, self.clock)
        try:
            row = conn.execute("SELECT id, owner_id FROM employees ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                owner_id = create_owner(conn, self.clock, owner_name)
                emp = create_employee(
                    conn, self.clock, owner_id=owner_id, name=employee_name, locale=locale, timezone=timezone
                )
                return owner_id, emp.id
            TaskEngine(conn, self.clock).recover_after_restart()
            conn.execute(  # A3-11: nobody is processing a request right after a restart
                "UPDATE request_receipts SET state = 'RECEIVED', lease_expires_at = NULL WHERE state = 'PROCESSING'"
            )
            return str(row[1]), str(row[0])
        finally:
            conn.close()

    def write_session(
        self, sessions: SessionRegistry, owner_id: str, employee_id: str, socket_path: Path
    ) -> Path:
        token = sessions.issue(Actor("owner", owner_id, "local_app", strong_auth=False), employee_id)
        path = self.ipc_dir / "session.json"
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "protocol": "1.0",
                    "socket": str(socket_path),
                    "owner_token": token,
                    "employee_id": employee_id,
                },
                f,
            )
        os.replace(tmp, path)
        return path

    def worker(self, employee_id: str, interval: float) -> None:
        _, broker, intel, artifacts = self._components()
        memory = MemoryManager(broker.conn, self.clock)
        verifier = Verifier(broker.conn, self.clock, artifacts)
        tools = [m.tool_id for m in BUILTIN_MANIFESTS]
        conversation = ConversationService(broker.conn, self.clock, broker, intel)
        guard = ProgressGuard(broker.tasks)
        scheduler = Scheduler(broker.tasks)
        self.monitor.started()
        try:
            self._loop(employee_id, interval, broker, intel, memory, verifier, tools, conversation, guard, scheduler)
        except BaseException as exc:  # the thread ends: say so instead of leaving health green
            self.monitor.stopped(f"{type(exc).__name__}: worker loop ended")
            raise
        self.monitor.stopped()

    def _loop(
        self,
        employee_id: str,
        interval: float,
        broker: Broker,
        intel: IntelligenceSetup,
        memory: MemoryManager,
        verifier: Verifier,
        tools: list[str],
        conversation: ConversationService,
        guard: ProgressGuard,
        scheduler: Scheduler,
    ) -> None:
        recovered = False
        while not self.stop.is_set():
            self.monitor.beat()
            broker.collect_late_results()
            try:
                client = intel.build_client()
            except AtlasError:
                self.stop.wait(interval)
                continue
            if not recovered:
                client.recover_attempts()
                recovered = True
            row = broker.conn.execute(
                "SELECT id FROM tasks WHERE employee_id = ? AND state IN ('CREATED','READY')"
                " ORDER BY CASE priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'NORMAL' THEN 2 ELSE 3 END,"
                " created_at LIMIT 1",
                (employee_id,),
            ).fetchone()
            if row is None:
                self.stop.wait(interval)
                continue
            inputs = broker.conn.execute(
                "SELECT COUNT(*) FROM artifact_links WHERE task_id = ? AND relation = 'input'", (row[0],)
            ).fetchone()[0]
            spec = DeliverableSpec(min_chars=200, min_sources=min(int(inputs), 5))
            runner = AgentRunner(
                broker.conn,
                self.clock,
                broker=broker,
                model=client,
                memory=memory,
                verifier=verifier,
                tools=tools,
                worker_id=f"worker-{os.getpid()}",
            )
            outcome = Core.run_one(runner, row[0], spec, self.monitor, broker.tasks)
            if outcome is None:
                self.stop.wait(interval)

    def watchdog(self, interval: float) -> None:
        """Independent housekeeping thread (A3-05, T21): reclaims expired leases, promotes retries and
        runs due scheduled jobs with its own connection, so a long task never stalls them."""
        wd = Watchdog(open_store(self.db_path, self.clock), self.clock)
        while not self.stop.wait(interval):
            try:
                wd.sweep()
            except Exception as exc:  # visible, never silent; the next sweep retries
                self.monitor.error(f"watchdog: {type(exc).__name__}")

    @staticmethod
    def run_one(
        runner: AgentRunner, task_id: str, spec: DeliverableSpec, monitor: WorkerMonitor, tasks: TaskEngine
    ) -> RunOutcome | None:
        """Run one task under a guard (A3-06). An unexpected error never ends the worker silently: it is
        journaled, shown by ``system.health`` and the task is reclaimed (fencing bumped) for recovery."""
        try:
            return runner.run(task_id, spec)
        except AtlasError:
            return None
        except Exception as exc:
            what = f"{type(exc).__name__} while running task {task_id}"
            monitor.error(what)
            try:
                state = ProgressGuard(tasks).reclaim_after_worker_loss(
                    task_id, f"worker error: {type(exc).__name__}"
                )
                emp = tasks.get(task_id)["employee_id"]
                with transaction(tasks.conn):
                    journal.append(
                        tasks.conn,
                        tasks.clock,
                        employee_id=emp,
                        task_id=task_id,
                        type="worker.error",
                        actor=Actor("system", "watchdog"),
                        summary=f"{what}; task reclaimed as {state or 'unchanged'}",
                    )
            except Exception as inner:  # diagnostics must not kill the worker either
                monitor.error(f"{what}; recovery failed with {type(inner).__name__}")
            return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atlas-core")
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--ipc-dir", type=Path, required=True)
    ap.add_argument("--owner-name", default="Proprietario")
    ap.add_argument("--employee-name", default="Atlas")
    ap.add_argument("--locale", default="pt-BR")
    ap.add_argument("--timezone", default="America/Sao_Paulo")
    ap.add_argument("--openai-base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--worker-interval", type=float, default=1.0)
    args = ap.parse_args(argv)
    if sys.platform == "win32":
        print("atlas-core requires macOS or Linux (Unix domain sockets)", file=sys.stderr)
        return 2
    core = Core(args.data_dir, args.ipc_dir, args.openai_base_url)
    owner_id, employee_id = core.bootstrap(args.owner_name, args.employee_name, args.locale, args.timezone)
    sessions = SessionRegistry()
    server = UnixSocketServer(args.ipc_dir, sessions, core.service)
    core.write_session(sessions, owner_id, employee_id, server.path)
    worker = threading.Thread(target=core.worker, args=(employee_id, args.worker_interval), daemon=True)
    worker.start()
    threading.Thread(target=core.watchdog, args=(max(args.worker_interval, 1.0),), daemon=True).start()

    def shutdown(signum: int, frame: FrameType | None) -> None:
        core.stop.set()
        server.close()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(json.dumps({"event": "ready", "socket": str(server.path), "vault": core.vault_reason}), flush=True)
    server.serve_forever()
    worker.join(timeout=5)
    (args.ipc_dir / "session.json").unlink(missing_ok=True)
    return 0
