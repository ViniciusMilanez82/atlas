"""AT-006.1/6.2: credential references, scoped release, no secret leakage."""

from __future__ import annotations

import io
import json
import logging
import pickle

import pytest

from security.vault.vault import SecretValue, Vault, VaultError, VaultUnavailable, platform_backend
from shared.actors import Actor
from shared.canonical import CanonicalizationError, canonical_bytes
from shared.redaction import RedactingFilter, Redactor
from tests.conftest import World
from tests.fakes.vault_backend import FakeInMemoryVaultBackend

SECRET = b"synthetic-test-key-000111222333"  # atlas-scan: allow-fake-secret
CP = Actor("control_plane", "broker")


@pytest.fixture
def vault(world: World) -> tuple[Vault, FakeInMemoryVaultBackend, Redactor]:
    backend = FakeInMemoryVaultBackend()
    red = Redactor()
    return Vault(world.conn, backend, world.clock, red), backend, red


def register(world: World, v: Vault, **kw: object) -> str:
    args: dict[str, object] = {
        "actor": world.owner,
        "employee_id": world.employee.id,
        "provider": "openai",
        "scope": "api",
        "purpose": "model_inference",
        "allowed_destinations": ["https://api.openai.com/*"],
        "secret": SECRET,
    }
    args.update(kw)
    return v.register(**args).id  # type: ignore[arg-type]


def test_database_stores_reference_not_secret(
    world: World, vault: tuple[Vault, FakeInMemoryVaultBackend, Redactor]
) -> None:
    v, backend, _ = vault
    register(world, v)
    assert len(backend) == 1
    dump = "\n".join(world.conn.iterdump())
    assert SECRET.decode() not in dump


def test_scoped_release_to_control_plane_only(
    world: World, vault: tuple[Vault, FakeInMemoryVaultBackend, Redactor]
) -> None:
    v, _, _ = vault
    ref = register(world, v)
    with v.use(
        ref, actor=CP, purpose="model_inference", destination="https://api.openai.com/v1/responses"
    ) as s:
        assert s.reveal() == SECRET
    for actor in (Actor("runtime", "rt"), Actor("worker", "w1"), world.owner):
        with (
            pytest.raises(VaultError, match="only to the Control Plane"),
            v.use(ref, actor=actor, purpose="model_inference", destination="https://api.openai.com/v1/x"),
        ):
            pass


@pytest.mark.parametrize(
    ("purpose", "destination", "msg"),
    [
        ("email_send", "https://api.openai.com/v1/x", "purpose"),
        ("model_inference", "https://attacker.example/collect", "destination"),
    ],
)
def test_wrong_purpose_or_destination_denied(
    world: World,
    vault: tuple[Vault, FakeInMemoryVaultBackend, Redactor],
    purpose: str,
    destination: str,
    msg: str,
) -> None:
    v, _, _ = vault
    ref = register(world, v)
    with pytest.raises(VaultError, match=msg), v.use(ref, actor=CP, purpose=purpose, destination=destination):
        pass


def test_revoked_and_expired_denied(
    world: World, vault: tuple[Vault, FakeInMemoryVaultBackend, Redactor]
) -> None:
    v, backend, _ = vault
    ref = register(world, v)
    v.revoke(ref, world.owner, world.employee.id)
    assert len(backend) == 0
    with (
        pytest.raises(VaultError, match="revoked"),
        v.use(ref, actor=CP, purpose="model_inference", destination="https://api.openai.com/v1/x"),
    ):
        pass
    ref2 = register(world, v, expires_at="2026-01-01T00:00:01.000Z")
    world.clock.advance(seconds=5)
    with (
        pytest.raises(VaultError, match="expired"),
        v.use(ref2, actor=CP, purpose="model_inference", destination="https://api.openai.com/v1/x"),
    ):
        pass


def test_only_owner_on_local_app_registers(
    world: World, vault: tuple[Vault, FakeInMemoryVaultBackend, Redactor]
) -> None:
    v, _, _ = vault
    for actor in (Actor("runtime", "rt"), Actor("owner", world.owner_id, "paired_device")):
        with pytest.raises(VaultError):
            register(world, v, actor=actor)


def test_missing_backend_secret_gives_diagnostic(
    world: World, vault: tuple[Vault, FakeInMemoryVaultBackend, Redactor]
) -> None:
    v, backend, _ = vault
    ref = register(world, v)
    backend._data.clear()
    with (
        pytest.raises(VaultError, match="re-authorize"),
        v.use(ref, actor=CP, purpose="model_inference", destination="https://api.openai.com/v1/x"),
    ):
        pass


def test_secret_value_never_renders() -> None:
    s = SecretValue(SECRET)
    assert SECRET.decode() not in repr(s)
    assert SECRET.decode() not in str(s)
    assert SECRET.decode() not in f"{s}"
    with pytest.raises(TypeError):
        pickle.dumps(s)
    with pytest.raises(TypeError):
        json.dumps(s)
    with pytest.raises(CanonicalizationError):
        canonical_bytes({"key": s})


def test_platform_backend_reports_diagnostic_instead_of_fallback() -> None:
    with pytest.raises(VaultUnavailable) as exc:
        platform_backend()
    assert "Keychain" in str(exc.value)


def test_used_secret_is_redacted_from_logs(
    world: World, vault: tuple[Vault, FakeInMemoryVaultBackend, Redactor]
) -> None:
    v, _, red = vault
    ref = register(world, v)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter(red))
    log = logging.getLogger("atlas.test.vault")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        with v.use(ref, actor=CP, purpose="model_inference", destination="https://api.openai.com/v1/x") as s:
            log.info("calling provider with %s", s.reveal().decode())
            try:
                raise RuntimeError("provider rejected key " + s.reveal().decode())
            except RuntimeError:
                log.exception("failure")
    finally:
        log.removeHandler(handler)
    out = stream.getvalue()
    assert SECRET.decode() not in out
    assert "[REDACTED]" in out


@pytest.mark.macos
def test_keychain_backend_round_trip(world: World) -> None:
    """REAL macOS Keychain through the Swift keychain service (AT-006.3). Runs on the macOS CI runner.

    Proves: the Vault stores only a reference in SQLite, the secret round-trips through the Keychain,
    revocation deletes it from the Keychain, a wrong session token is rejected. It does NOT prove the
    Supervisor lifecycle (launchd/SMAppService) on the owner's Mac.
    """
    import os
    import shutil
    import subprocess
    import tempfile
    import time
    import uuid
    from pathlib import Path

    from security.vault.keychain_backend import KeychainAgentBackend, KeychainAgentError

    agent = os.environ.get("ATLAS_KEYCHAIN_AGENT")
    if not agent or not Path(agent).is_file():
        pytest.skip("NAO EXECUTADO: build platform/macos/AtlasKit and set ATLAS_KEYCHAIN_AGENT")
    short = Path(tempfile.mkdtemp(prefix="akc", dir="/tmp"))
    os.chmod(short, 0o700)
    token_file = short / "token"
    token = uuid.uuid4().hex
    token_file.write_text(token, encoding="utf-8")
    os.chmod(token_file, 0o600)
    sock = short / "kc.sock"
    service = f"com.atlas.tests.vault.{uuid.uuid4().hex}"
    proc = subprocess.Popen([agent, str(sock), str(token_file), service])
    try:
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.05)
        backend = KeychainAgentBackend(sock, token)
        vault = Vault(world.conn, backend, world.clock, Redactor())
        ref = register(world, vault)
        assert SECRET.decode() not in "\n".join(world.conn.iterdump())  # DB holds only the reference
        with vault.use(
            ref, actor=CP, purpose="model_inference", destination="https://api.openai.com/v1/responses"
        ) as s:
            assert s.reveal() == SECRET  # really came back from the Keychain
        locator = world.conn.execute(
            "SELECT backend_locator FROM credential_refs WHERE id=?", (ref,)
        ).fetchone()[0]
        assert backend.get(locator) == SECRET
        vault.revoke(ref, world.owner, world.employee.id)
        assert backend.get(locator) is None  # deleted from the Keychain
        with pytest.raises(KeychainAgentError):
            KeychainAgentBackend(sock, "wrong-token").get(locator)
    finally:
        proc.terminate()
        proc.wait(5)
        shutil.rmtree(short, ignore_errors=True)


def test_platform_backend_needs_configured_service_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_KEYCHAIN_SOCKET", raising=False)
    monkeypatch.delenv("ATLAS_KEYCHAIN_TOKEN_FILE", raising=False)
    with pytest.raises(VaultUnavailable):
        platform_backend()
