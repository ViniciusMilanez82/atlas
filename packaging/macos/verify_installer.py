"""Install and reinstall the Alpha on a disposable macOS GitHub-hosted runner.

Never included in the user-facing installer. Refuses other environments and preexisting apps/data.
Only synthetic data is used; no API key, network research or microphone is enabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path

from prepare_installer import BUNDLE_ID, manifest


def run(command: list[str], *, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}:\n{result.stdout[-12000:]}")
    return result


def data_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pkg", type=Path, required=True)
    parser.add_argument("--dmg", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if (os.environ.get("GITHUB_ACTIONS") != "true" or platform.system() != "Darwin"
            or os.environ.get("GITHUB_REPOSITORY") != "ViniciusMilanez82/atlas"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or os.geteuid() == 0):
        raise RuntimeError("This installation test is restricted to the disposable GitHub-hosted macOS runner.")
    installed = Path("/Applications/Atlas.app")
    data = Path.home() / "Library/Application Support/Atlas"
    if installed.exists() or data.exists():
        raise RuntimeError("Refusing to replace a preexisting application or user data in a test.")
    args.evidence.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True)
    sentinel = data / "installer-preservation-test.txt"
    sentinel.write_text("SYNTHETIC INSTALLER TEST ONLY\n", encoding="ascii")
    expected = json.loads(args.manifest.read_text())
    report = {"schema": 1, "source_commit": os.environ.get("GITHUB_SHA"),
              "macos": platform.mac_ver()[0], "architecture": platform.machine(),
              "notarized": False, "complete_v1": False, "real_provider_tested": False,
              "interactive_human_tested": False, "checks": {}}
    mounted = False
    with tempfile.TemporaryDirectory(prefix="atlas-install-") as tmp:
        mount = Path(tmp) / "disk"
        mount.mkdir()
        try:
            run(["/usr/bin/hdiutil", "verify", str(args.dmg)])
            run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(args.dmg)])
            mounted = True
            pkg = mount / "Instalar Atlas.pkg"
            if hashlib.sha256(pkg.read_bytes()).digest() != hashlib.sha256(args.pkg.read_bytes()).digest():
                raise RuntimeError("The package inside the DMG differs from the standalone package.")
            report["checks"]["dmg_readonly_and_package_hash"] = True
            expanded = Path(tmp) / "expanded"
            run(["/usr/sbin/pkgutil", "--expand-full", str(pkg), str(expanded)])
            if any(p.name == "Scripts" for p in expanded.rglob("*")):
                raise RuntimeError("User-facing installer must not have pre/postinstall scripts.")
            payloads = list(expanded.rglob("Payload"))
            if len(payloads) != 1 or not payloads[0].is_dir():
                raise RuntimeError("Expected a single application-only package payload.")
            staged = payloads[0] / "Applications/Atlas.app"
            for path in payloads[0].iterdir():
                if path.name != "Applications":
                    raise RuntimeError("Package writes outside Applications.")
            if list((payloads[0] / "Applications").iterdir()) != [staged]:
                raise RuntimeError("Package includes unrelated applications.")
            if manifest(staged)["files"] != expected["files"]:
                raise RuntimeError("Expanded package payload differs from the input signed app.")
            report["checks"]["payload_app_only_no_scripts"] = True
            # Capture the actual Installer welcome page; not a synthetic mock-up, not a human test.
            try:
                run(["/usr/bin/open", "-a", "Installer", str(pkg)], timeout=20)
                time.sleep(4)
                run(["/usr/sbin/screencapture", "-x", str(args.evidence / "installer-window.png")], timeout=10)
                report["installer_screenshot"] = "captured"
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                report["installer_screenshot"] = f"unavailable: {type(exc).__name__}"
            finally:
                run(["/usr/bin/osascript", "-e", 'tell application "Installer" to quit'], timeout=20, check=False)
            # No -allowUntrusted flag and no Gatekeeper/quarantine changes. CLI installation is
            # not evidence that Gatekeeper will allow the download on the owner's Mac.
            first = run(["/usr/bin/sudo", "-n", "/usr/sbin/installer", "-pkg", str(pkg), "-target", "/"], timeout=300)
            (args.evidence / "install-first.log").write_text(first.stdout)
            if manifest(installed)["files"] != expected["files"]:
                raise RuntimeError("Installed app differs from the packaged app.")
            run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(installed)])
            report["checks"]["installed_at_applications_signature_intact"] = True
            run(["/usr/bin/open", str(installed)], timeout=20)
            time.sleep(20)
            try:
                run(["/usr/sbin/screencapture", "-x", str(args.evidence / "installed-atlas-window.png")], timeout=10)
                report["app_screenshot"] = "captured"
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                report["app_screenshot"] = f"unavailable: {type(exc).__name__}"
            run(["/usr/bin/osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'], timeout=30)
            deadline = time.monotonic() + 20
            while run(["/usr/bin/pgrep", "-f", "/Applications/Atlas.app/Contents/"], check=False).returncode == 0:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Installed Atlas services did not terminate before reinstall.")
                time.sleep(0.2)
            before = data_hashes(data)
            if len(before) < 2 or not any(name.endswith(".sqlite") or name.endswith(".db") for name in before):
                raise RuntimeError("The installed UI did not initialize a real local database.")
            report["checks"]["installed_ui_created_local_database_and_quit"] = True
            second = run(["/usr/bin/sudo", "-n", "/usr/sbin/installer", "-pkg", str(pkg), "-target", "/"], timeout=300)
            (args.evidence / "install-second.log").write_text(second.stdout)
            if data_hashes(data) != before or sentinel.read_text() != "SYNTHETIC INSTALLER TEST ONLY\n":
                raise RuntimeError("Reinstall changed the existing synthetic user data.")
            report["checks"]["reinstall_preserves_existing_data"] = True
            # Exercise real Supervisor + Keychain + IPC from the INSTALLED app with no system Python.
            probe = run(["/usr/bin/env", "-i", f"HOME={Path.home()}", "PATH=/usr/bin:/bin",
                         str(args.probe), str(installed)], timeout=90)
            result = json.loads(probe.stdout)
            if result["health"]["components"]["database"] != "ok":
                raise RuntimeError("Installed bundle database probe failed.")
            if result["health"]["components"]["intelligence"] != "not_configured":
                raise RuntimeError("Installer test must not contain a paid provider credential.")
            (args.evidence / "installed-bundle-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
            report["checks"]["installed_bundle_without_system_python"] = True
            run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(installed)])
            # Read-only assessment: record the real rejection, do not suppress it or change settings.
            assessment = run(["/usr/sbin/spctl", "--assess", "--type", "install", "--verbose=4", str(pkg)], check=False)
            (args.evidence / "gatekeeper-assessment.log").write_text(assessment.stdout)
            report["gatekeeper_assessment_exit"] = assessment.returncode
            report["status"] = "installation-tests-passed-not-a-production-release"
        except Exception as exc:
            report["status"] = "failed"
            report["error"] = str(exc)
            raise
        finally:
            if mounted:
                run(["/usr/bin/hdiutil", "detach", str(mount)], check=False)
            (args.evidence / "installer-test-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
