"""FAKE module-level adapters for process-isolated execution tests (must be picklable)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def sleep_forever(tool_input: dict[str, Any]) -> dict[str, Any]:
    while True:
        time.sleep(0.05)


def write_marker_then_hang(tool_input: dict[str, Any]) -> dict[str, Any]:
    Path(tool_input["path"]).write_text("effect happened", encoding="utf-8")
    while True:
        time.sleep(0.05)


def quick(tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"status": "SUCCEEDED", "output": {"echo": tool_input["path"]}}
