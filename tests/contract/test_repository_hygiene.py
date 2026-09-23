"""AT-001 hygiene: preserved specification, required docs, no secrets, no host shell tool."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOCS = [
    "docs/MASTER_SPEC.md",
    "docs/ARCHITECTURE.md",
    "docs/THREAT_MODEL.md",
    "docs/REQUIREMENTS_TRACEABILITY.md",
    "docs/BUILD_AND_RUN.md",
    "docs/PROGRESS.md",
    "docs/OPERATIONS.md",
    "docs/BACKLOG.md",
    "docs/EXTERNAL_DEPENDENCIES.md",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_master_spec_is_byte_identical_to_received_spec() -> None:
    received = ROOT / "docs" / "spec" / "Atlas_Especificacao_Tecnica_v1_0.md"
    assert sha256(ROOT / "docs" / "MASTER_SPEC.md") == sha256(received)


def test_received_spec_files_match_recorded_hashes() -> None:
    sums = (ROOT / "docs" / "spec" / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(sums) == 4
    for line in sums:
        digest, name = line.split(maxsplit=1)
        assert sha256(ROOT / "docs" / "spec" / name.lstrip("*")) == digest, name


@pytest.mark.parametrize("rel", REQUIRED_DOCS)
def test_required_doc_exists_and_has_content(rel: str) -> None:
    path = ROOT / rel
    assert path.is_file(), rel
    assert len(path.read_text(encoding="utf-8").strip()) > 200, rel


def test_adrs_exist_for_initial_decisions() -> None:
    names = sorted(p.name for p in (ROOT / "docs" / "ADR").glob("ADR-*.md"))
    for n in range(1, 9):
        assert any(name.startswith(f"ADR-{n:03d}") for name in names), f"ADR-{n:03d} missing"


def test_secret_scan_is_clean() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/scan_secrets.py"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout


def test_secret_scanner_detects_planted_key(tmp_path: Path) -> None:
    planted = tmp_path / "leak.py"
    planted.write_text('OPENAI = "sk-proj-' + "A" * 40 + '"\n', encoding="utf-8")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import scan_secrets
    finally:
        sys.path.pop(0)
    original = scan_secrets.ROOT
    scan_secrets.ROOT = tmp_path
    try:
        assert scan_secrets.scan([planted]) == [("leak.py", 1, "openai_key")]
    finally:
        scan_secrets.ROOT = original


def test_no_production_code_spawns_a_host_shell() -> None:
    """Spec 5.4 / 10.1: no free shell on the host. Production packages must not use shell=True,
    os.system or os.popen. Dev scripts under scripts/ are excluded (they run on the developer box)."""
    offenders = []
    for pkg in ("shared", "storage", "security", "runtime"):
        for path in (ROOT / pkg).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in ("shell=True", "os.system(", "os.popen(", "import subprocess"):
                if needle in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {needle}")
    assert offenders == []


def test_test_fakes_are_not_importable_from_production_packages() -> None:
    offenders = []
    for pkg in ("shared", "storage", "security", "runtime"):
        for path in (ROOT / pkg).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "tests.fakes" in text or "from tests" in text:
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
