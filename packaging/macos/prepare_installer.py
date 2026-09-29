"""Prepare a script-free, offline macOS Installer distribution for the existing Alpha.

No installer action downloads software, executes a shell, starts Atlas, or changes Gatekeeper.
The native macOS package tools supply the actual install transaction and OS/architecture checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

BUNDLE_ID = "com.atlas.digital-employee.dev"
PACKAGE_ID = "com.atlas.digital-employee.dev.installer"
MINIMUM_OS = "15.0"
COMPONENT = "AtlasComponent.pkg"


def version_for_build(build: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]{0,8}", build):
        raise ValueError("build must be a positive integer with at most 9 digits")
    return f"0.1.{build}"


def validate_bundle(app: Path) -> dict:
    """Reject wrong apps, missing embedded runtimes, and escaping symlinks before staging."""
    if app.is_symlink() or not app.is_dir() or app.name != "Atlas.app":
        raise ValueError("expected the real Atlas.app directory, not a symlink")
    base = app.resolve()
    with (base / "Contents/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundleExecutable") != "Atlas":
        raise ValueError("unexpected application identity")
    if info.get("LSMinimumSystemVersion") != MINIMUM_OS:
        raise ValueError("installer and application minimum macOS must agree")
    for relative in (
        "Contents/MacOS/Atlas", "Contents/MacOS/atlas-keychain-agent",
        "Contents/Resources/python/bin/python3", "Contents/Resources/core-src/core/__main__.py",
        "Contents/Resources/sbom.cdx.json",
    ):
        target = base / relative
        if not target.is_file() or not target.resolve().is_relative_to(base):
            raise ValueError(f"required bundle member missing or escaping: {relative}")
    for member in base.rglob("*"):
        if member.is_symlink() and (not member.exists() or not member.resolve().is_relative_to(base)):
            raise ValueError(f"external or broken symlink in bundle: {member.relative_to(base)}")
    return info


def distribution(build: str) -> ET.Element:
    version = version_for_build(build)
    root = ET.Element("installer-gui-script", minSpecVersion="2")
    ET.SubElement(root, "title").text = "Atlas — instalação de desenvolvimento"
    ET.SubElement(root, "options", {
        "customize": "never", "require-scripts": "false", "allow-external-scripts": "false",
        "hostArchitectures": "arm64",
    })
    ET.SubElement(root, "domains", {
        "enable_anywhere": "false", "enable_currentUserHome": "false", "enable_localSystem": "true",
    })
    check = ET.SubElement(root, "volume-check", script="true")
    ET.SubElement(ET.SubElement(check, "allowed-os-versions"), "os-version", min=MINIMUM_OS)
    for tag, filename in (("welcome", "Welcome.html"), ("readme", "ReadMe.html"), ("conclusion", "Conclusion.html")):
        ET.SubElement(root, tag, file=filename, **{"mime-type": "text/html"})
    outline = ET.SubElement(root, "choices-outline")
    ET.SubElement(outline, "line", choice="atlas")
    choice = ET.SubElement(root, "choice", id="atlas", title="Atlas", visible="false", selected="true")
    ET.SubElement(choice, "pkg-ref", id=PACKAGE_ID)
    ET.SubElement(root, "pkg-ref", id=PACKAGE_ID, version=version, onConclusion="None").text = COMPONENT
    must_close = ET.SubElement(ET.SubElement(root, "pkg-ref", id=PACKAGE_ID), "must-close")
    ET.SubElement(must_close, "app", id=BUNDLE_ID)
    return root


def components() -> list[dict]:
    return [{
        "RootRelativeBundlePath": "Applications/Atlas.app",
        "BundleHasStrictIdentifier": True,
        "BundleIsRelocatable": False,
        # Existing Alpha bundles used Git hashes as CFBundleVersion. Native package versions are
        # numeric; do not compare incompatible legacy bundle hashes as release versions.
        # This preview package permits reinstall, NOT an automatic production updater.
        "BundleIsVersionChecked": False,
        "BundleOverwriteAction": "upgrade",
    }]


def manifest(app: Path) -> dict:
    info = validate_bundle(app)
    entries = []
    for path in sorted(app.rglob("*")):
        relative = path.relative_to(app).as_posix()
        if path.is_symlink():
            entries.append({"path": relative, "symlink": str(path.readlink())})
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            entries.append({"path": relative, "sha256": digest.hexdigest(), "size": path.stat().st_size})
    return {
        "schema": 1, "channel": "development-alpha", "notarized": False,
        "bundle_id": BUNDLE_ID, "source_bundle_version": info.get("CFBundleVersion"),
        "minimum_macos": MINIMUM_OS, "architecture": "arm64", "files": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--build", required=True)
    args = parser.parse_args()
    validate_bundle(args.app)
    args.work.mkdir(parents=True, exist_ok=True)
    tree = distribution(args.build)
    ET.indent(tree)
    ET.ElementTree(tree).write(args.work / "Distribution.xml", encoding="utf-8", xml_declaration=True)
    (args.work / "components.plist").write_bytes(plistlib.dumps(components()))
    (args.work / "bundle-manifest.json").write_text(
        json.dumps(manifest(args.app), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.work / "package-version.txt").write_text(version_for_build(args.build), encoding="ascii")


if __name__ == "__main__":
    main()
