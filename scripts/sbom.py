"""Software bill of materials for the runtime bundled in Atlas.app (N23, spec 23.3, 28).

Reads the pinned runtime lock and the installed distributions (the bundle's site-packages, or the current
environment) and writes a CycloneDX 1.5 JSON document: name, exact version, purl and declared license of
every runtime package. A package in the lock that is not installed, or installed with another version, is
an error - the SBOM must describe what is really shipped.

    python scripts/sbom.py --lock packaging/macos/runtime-requirements.lock [--site DIR] [--out FILE]
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _license(dist: md.Distribution) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return str(expr)
    lic = meta.get("License") or ""
    if lic and len(lic) < 80 and "\n" not in lic:
        return str(lic)
    classifiers = [
        c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    return "; ".join(classifiers) or "UNKNOWN"


def build(lock: Path, site: Path | None) -> dict[str, object]:
    pins = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, version = line.partition("==")
            pins[_norm(name)] = (name, version)
    dists = md.distributions(path=[str(site)]) if site else md.distributions()
    installed = {_norm(d.metadata["Name"]): d for d in dists}
    components = []
    errors = []
    for key, (name, version) in sorted(pins.items()):
        dist = installed.get(key)
        if dist is None:
            errors.append(f"{name}=={version} is in the lock but not installed")
            continue
        if dist.version != version:
            errors.append(f"{name}: lock says {version}, installed {dist.version}")
        components.append(
            {
                "type": "library",
                "name": name,
                "version": dist.version,
                "purl": f"pkg:pypi/{key}@{dist.version}",
                "licenses": [{"license": {"name": _license(dist)}}],
            }
        )
    if errors:
        raise SystemExit("SBOM refused:\n" + "\n".join(errors))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {"type": "application", "name": "Atlas (atlas-core runtime)"},
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lock", type=Path, required=True)
    ap.add_argument("--site", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    doc = json.dumps(build(args.lock, args.site), indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(doc + "\n", encoding="utf-8")
    else:
        sys.stdout.write(doc + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
