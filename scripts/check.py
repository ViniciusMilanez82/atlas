"""Single entry point for local verification: lint, types, secret scan, tests.

Usage:  python scripts/check.py            (everything available on this host)
        python scripts/check.py --fast     (skip mypy)

Prints each command and its exit status so results can be pasted into PROGRESS.md as evidence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(label: str, cmd: list[str]) -> int:
    print(f"\n=== {label}: {' '.join(cmd)}", flush=True)
    code = subprocess.run(cmd, cwd=ROOT, check=False).returncode
    print(f"=== {label}: exit {code}", flush=True)
    return code


def main() -> int:
    fast = "--fast" in sys.argv
    steps: list[tuple[str, list[str]]] = [
        ("ruff", [PY, "-m", "ruff", "check", "."]),
        ("secrets", [PY, "scripts/scan_secrets.py"]),
    ]
    if not fast:
        steps.append(("mypy", [PY, "-m", "mypy"]))
    steps.append(("pytest", [PY, "-m", "pytest", "-q"]))
    results = {label: run(label, cmd) for label, cmd in steps}
    print("\nSUMMARY: " + ", ".join(f"{k}={'PASS' if v == 0 else 'FAIL'}" for k, v in results.items()))
    return 0 if all(v == 0 for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
