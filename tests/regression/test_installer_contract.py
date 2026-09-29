"""N23: package contract tests. These do not replace real macOS installation tests."""
from __future__ import annotations

import hashlib
import importlib.util
import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("atlas_prepare_installer", ROOT / "packaging/macos/prepare_installer.py")
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@pytest.fixture
def fake_app(tmp_path: Path) -> Path:
    app = tmp_path / "Atlas.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": installer.BUNDLE_ID, "CFBundleExecutable": "Atlas",
        "CFBundleVersion": "synthetic-test", "LSMinimumSystemVersion": "15.0",
    }))
    for member in ("Contents/MacOS/Atlas", "Contents/MacOS/atlas-keychain-agent",
                   "Contents/Resources/python/bin/python3", "Contents/Resources/core-src/core/__main__.py",
                   "Contents/Resources/sbom.cdx.json"):
        path = app / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test-only")
    return app


@pytest.mark.parametrize("build", ["0", "-1", "01", "1;exit", "", "1000000000", "1.2"])
def test_invalid_build_is_rejected(build: str) -> None:
    with pytest.raises(ValueError):
        installer.distribution(build)


def test_native_requirements_no_scripts_no_restart() -> None:
    root = installer.distribution("81")
    options = root.find("options")
    assert options is not None
    assert options.attrib["hostArchitectures"] == "arm64"
    assert options.attrib["require-scripts"] == "false"
    assert options.attrib["allow-external-scripts"] == "false"
    assert root.find("script") is None
    minimum = root.find("volume-check/allowed-os-versions/os-version")
    assert minimum is not None and minimum.attrib["min"] == "15.0"
    assert root.find("domains").attrib == {
        "enable_anywhere": "false", "enable_currentUserHome": "false", "enable_localSystem": "true"}
    assert root.find("pkg-ref/must-close/app").attrib["id"] == installer.BUNDLE_ID
    refs = [r for r in root.findall("pkg-ref") if r.text]
    assert len(refs) == 1 and refs[0].text == "AtlasComponent.pkg"
    assert refs[0].attrib["onConclusion"] == "None"
    assert refs[0].attrib["version"] == "0.1.81"


def test_package_is_nonrelocatable_and_app_only() -> None:
    component, = installer.components()
    assert component["RootRelativeBundlePath"] == "Applications/Atlas.app"
    assert component["BundleIsRelocatable"] is False
    assert component["BundleHasStrictIdentifier"] is True
    assert component["BundleOverwriteAction"] == "upgrade"


def test_real_bundle_is_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        installer.validate_bundle(tmp_path / "Atlas.app")


def test_wrong_app_is_refused(fake_app: Path) -> None:
    path = fake_app / "Contents/Info.plist"
    data = plistlib.loads(path.read_bytes())
    data["CFBundleIdentifier"] = "com.other.product"
    path.write_bytes(plistlib.dumps(data))
    with pytest.raises(ValueError, match="identity"):
        installer.validate_bundle(fake_app)


def test_os_requirement_matches_bundle(fake_app: Path) -> None:
    path = fake_app / "Contents/Info.plist"
    data = plistlib.loads(path.read_bytes())
    data["LSMinimumSystemVersion"] = "16.0"
    path.write_bytes(plistlib.dumps(data))
    with pytest.raises(ValueError, match="minimum"):
        installer.validate_bundle(fake_app)


def test_runtime_cannot_be_external(fake_app: Path, tmp_path: Path) -> None:
    outside = tmp_path / "external-python"
    outside.write_bytes(b"do-not-copy")
    runtime = fake_app / "Contents/Resources/python/bin/python3"
    runtime.unlink()
    runtime.symlink_to(outside)
    with pytest.raises(ValueError, match="escaping"):
        installer.validate_bundle(fake_app)


def test_other_external_symlinks_are_refused(fake_app: Path, tmp_path: Path) -> None:
    (fake_app / "external").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        installer.validate_bundle(fake_app)


def test_manifest_tracks_bytes_and_never_claims_notarization(fake_app: Path) -> None:
    before = installer.manifest(fake_app)
    assert before["notarized"] is False and before["channel"] == "development-alpha"
    assert before == installer.manifest(fake_app)
    exe = next(item for item in before["files"] if item["path"] == "Contents/MacOS/Atlas")
    assert exe["sha256"] == hashlib.sha256(b"test-only").hexdigest()
    (fake_app / "Contents/MacOS/Atlas").write_bytes(b"changed")
    assert before != installer.manifest(fake_app)


def test_guides_are_offline_and_disclose_scope() -> None:
    resources = ROOT / "packaging/macos/installer-resources"
    for name in ("Welcome.html", "ReadMe.html", "Conclusion.html"):
        text = (resources / name).read_text()
        assert 'lang="pt-BR"' in text and "Alpha" in text
        assert "<script" not in text.lower()
        assert "<iframe" not in text.lower()
        assert "<img" not in text.lower()
    text = (resources / "ReadMe.html").read_text()
    assert "não foi notarizado" in text and "Ainda faltam" in text
    assert "não prossiga" in text and "Intel" in text
