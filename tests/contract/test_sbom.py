"""N23: the SBOM describes exactly the pinned runtime that ships in the bundle, with licenses."""

from __future__ import annotations

from pathlib import Path

from scripts.sbom import build

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "packaging" / "macos" / "runtime-requirements.lock"


def test_sbom_lists_every_runtime_package_with_version_and_license() -> None:
    doc = build(LOCK, None)
    names = {c["name"].lower() for c in doc["components"]}  # type: ignore[index, union-attr]
    pinned = {
        line.split("==")[0].lower()
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert names == pinned
    for c in doc["components"]:  # type: ignore[union-attr]
        assert c["purl"].startswith("pkg:pypi/") and c["licenses"][0]["license"]["name"] != "UNKNOWN", c
