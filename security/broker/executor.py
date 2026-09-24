"""Deadline-enforcing tool execution (spec 9.4, 12.2, 12.3; review finding R-03).

Two isolation modes, declared by the trusted manifest:

* ``thread``: trusted, cooperative adapters of the control plane. The broker waits at most
  ``timeout_s``; then it sets the cancellation event and waits a short grace period for the adapter
  to acknowledge. A Python thread cannot be killed, so an adapter that ignores cancellation keeps
  running in the background; its eventual result is delivered to ``on_late`` and recorded as a
  late completion. The broker itself never blocks beyond deadline + grace.
* ``process``: non-cooperative code. Runs in a child process that is terminated (then killed) at
  the deadline, so the operation really stops. This is resource containment, **not** a security
  sandbox: the child runs as the same OS user. Untrusted code belongs in the Execution Box / guest
  VM (M8, requires D-01). Process tools never receive credentials.

Cancelling the wait is never confused with cancelling the operation: if the effect may have
happened, the result is UNKNOWN and goes to reconciliation, never to a blind retry.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_GRACE_S = 2.0
MAX_TIMEOUT_S = 600.0


@dataclass
class ExecutionReport:
    finished: bool  # the adapter returned (or raised) before deadline + grace
    value: Any = None  # adapter return value when finished without exception
    error: BaseException | None = None
    timed_out: bool = False
    cancel_acknowledged: bool = False  # finished only after cancellation was requested
    killed: bool = False  # process mode: the child was terminated


def run_in_thread(
    fn: Callable[[], Any],
    *,
    timeout_s: float,
    cancel_event: threading.Event,
    grace_s: float = DEFAULT_GRACE_S,
    on_late: Callable[[Any, BaseException | None], None] | None = None,
) -> ExecutionReport:
    timeout_s = max(0.0, min(timeout_s, MAX_TIMEOUT_S))
    done = threading.Event()
    box: dict[str, Any] = {}
    late_lock = threading.Lock()
    state = {"abandoned": False}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc
        with late_lock:
            abandoned = state["abandoned"]
            done.set()
        if abandoned and on_late is not None:
            on_late(box.get("value"), box.get("error"))

    worker = threading.Thread(target=target, name="atlas-tool", daemon=True)
    worker.start()
    if done.wait(timeout_s):
        return ExecutionReport(True, box.get("value"), box.get("error"))
    cancel_event.set()
    if done.wait(grace_s):
        return ExecutionReport(
            True, box.get("value"), box.get("error"), timed_out=True, cancel_acknowledged=True
        )
    with late_lock:
        if done.is_set():  # finished in the tiny window between wait and lock
            return ExecutionReport(
                True, box.get("value"), box.get("error"), timed_out=True, cancel_acknowledged=True
            )
        state["abandoned"] = True
    return ExecutionReport(False, timed_out=True)


def _child(fn: Callable[[dict[str, Any]], Any], tool_input: dict[str, Any], out: Any) -> None:
    try:
        out.put(("ok", fn(tool_input)))
    except BaseException as exc:
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def run_in_process(
    fn: Callable[[dict[str, Any]], Any], tool_input: dict[str, Any], *, timeout_s: float
) -> ExecutionReport:
    """``fn`` must be a picklable module-level function. The child gets only the tool input."""
    timeout_s = max(0.0, min(timeout_s, MAX_TIMEOUT_S))
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    proc = ctx.Process(target=_child, args=(fn, tool_input, out), daemon=True)
    proc.start()
    # Read BEFORE joining (finding B-01): a large result blocks the child's queue feeder until the parent
    # reads it, so joining first would kill a healthy child at the deadline.
    try:
        kind, payload = out.get(timeout=timeout_s)
    except Exception:  # deadline reached, or the child died without reporting
        if proc.is_alive():
            proc.terminate()
            proc.join(2)
            if proc.is_alive():
                proc.kill()
                proc.join(2)
            return ExecutionReport(False, timed_out=True, killed=True)
        proc.join(2)
        return ExecutionReport(True, error=RuntimeError(f"tool process exited with code {proc.exitcode}"))
    proc.join(5)
    if kind == "ok":
        return ExecutionReport(True, value=payload)
    return ExecutionReport(True, error=RuntimeError(str(payload)))
