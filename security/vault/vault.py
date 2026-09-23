"""Credential Vault (spec 11.4, AT-006).

The database stores only ``credential_refs`` metadata. Raw secrets live in a platform backend
(production: macOS Keychain through the Swift Supervisor - NOT AVAILABLE on this host, see
ADR-009). A secret is released only to the broker, for one declared purpose and one allowed
destination, inside a context manager. There is deliberately no ``read_secret`` operation that
returns a plain string, and ``SecretValue`` refuses to be printed, serialized or hashed into
canonical payloads.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from shared.actors import Actor
from shared.clock import Clock, parse_utc, to_utc_str
from shared.ids import new_id
from shared.redaction import Redactor, default_redactor
from storage import journal
from storage.db import transaction


class VaultError(RuntimeError):
    pass


class VaultUnavailable(VaultError):
    """No secure backend on this platform. Diagnostic, not a fallback trigger."""


class VaultBackend(Protocol):
    name: str

    def put(self, locator: str, secret: bytes) -> None: ...

    def get(self, locator: str) -> bytes | None: ...

    def delete(self, locator: str) -> None: ...


class SecretValue:
    """Opaque holder. ``reveal()`` is the only way to read it; it never renders as text."""

    __slots__ = ("__value",)

    def __init__(self, value: bytes) -> None:
        self.__value = value

    def reveal(self) -> bytes:
        return self.__value

    def __repr__(self) -> str:
        return "SecretValue([REDACTED])"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("SecretValue cannot be pickled")

    def __eq__(self, other: object) -> bool:
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]


@dataclass(frozen=True)
class CredentialRef:
    id: str
    owner_id: str
    provider: str
    scope: str
    purpose: str
    allowed_destinations: tuple[str, ...]
    backend: str
    expires_at: str | None
    revoked_at: str | None


def platform_backend() -> VaultBackend:
    """Return the production backend for this platform or raise an actionable diagnostic."""
    import sys

    if sys.platform == "darwin":
        from security.vault.keychain_backend import from_environment

        backend = from_environment()
        if backend is None:
            raise VaultUnavailable(
                "Keychain service not configured: the Supervisor must start atlas-keychain-agent and set "
                "ATLAS_KEYCHAIN_SOCKET and ATLAS_KEYCHAIN_TOKEN_FILE."
            )
        return backend
    raise VaultUnavailable(
        f"No secure credential backend for platform {sys.platform!r}. The Atlas product targets macOS "
        "Keychain; on this development host only synthetic test credentials may be used."
    )


class Vault:
    def __init__(
        self,
        conn: sqlite3.Connection,
        backend: VaultBackend,
        clock: Clock,
        redactor: Redactor | None = None,
    ) -> None:
        self._conn = conn
        self._backend = backend
        self._clock = clock
        self._redactor = redactor or default_redactor

    def register(
        self,
        *,
        actor: Actor,
        employee_id: str,
        provider: str,
        scope: str,
        purpose: str,
        allowed_destinations: list[str],
        secret: bytes,
        expires_at: str | None = None,
    ) -> CredentialRef:
        """Store a secret supplied by the owner. Only the owner, on the local app, may do this."""
        if actor.kind != "owner" or actor.channel != "local_app":
            raise VaultError("only the owner on the local app can register credentials")
        if not allowed_destinations:
            raise VaultError("a credential needs at least one allowed destination")
        ref_id = new_id()
        locator = f"atlas.{provider}.{ref_id}"
        self._backend.put(locator, secret)
        now = to_utc_str(self._clock.now())
        try:
            with transaction(self._conn):
                self._conn.execute(
                    "INSERT INTO credential_refs(id, owner_id, provider, scope, purpose,"
                    " allowed_destinations_json, backend, backend_locator, expires_at, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        ref_id,
                        actor.id,
                        provider,
                        scope,
                        purpose,
                        json.dumps(allowed_destinations),
                        self._backend.name,
                        locator,
                        expires_at,
                        now,
                    ),
                )
                journal.append(
                    self._conn,
                    self._clock,
                    employee_id=employee_id,
                    type="credential.registered",
                    actor=actor,
                    summary=f"credential_ref {ref_id} for {provider}/{purpose}",
                )
        except Exception:
            self._backend.delete(locator)
            raise
        return self.get_ref(ref_id)

    def get_ref(self, ref_id: str) -> CredentialRef:
        row = self._conn.execute("SELECT * FROM credential_refs WHERE id = ?", (ref_id,)).fetchone()
        if row is None:
            raise VaultError("unknown credential_ref")
        return CredentialRef(
            id=row["id"],
            owner_id=row["owner_id"],
            provider=row["provider"],
            scope=row["scope"],
            purpose=row["purpose"],
            allowed_destinations=tuple(json.loads(row["allowed_destinations_json"])),
            backend=row["backend"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    def find_ref(self, *, purpose: str, destination: str) -> str:
        """The single active credential for this purpose whose destinations cover ``destination``."""
        matches = []
        rows = self._conn.execute(
            "SELECT id FROM credential_refs WHERE purpose = ? AND revoked_at IS NULL", (purpose,)
        ).fetchall()
        for row in rows:
            ref = self.get_ref(row["id"])
            if any(fnmatch.fnmatchcase(destination, pat) for pat in ref.allowed_destinations):
                matches.append(ref.id)
        if not matches:
            raise VaultError("no credential configured for this purpose and destination")
        if len(matches) > 1:
            raise VaultError("more than one credential matches; the owner must disambiguate")
        return matches[0]

    def revoke(self, ref_id: str, actor: Actor, employee_id: str) -> None:
        if actor.kind != "owner":
            raise VaultError("only the owner can revoke credentials")
        row = self._conn.execute(
            "SELECT backend_locator FROM credential_refs WHERE id = ?", (ref_id,)
        ).fetchone()
        if row is None:
            raise VaultError("unknown credential_ref")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE credential_refs SET revoked_at = ? WHERE id = ?",
                (to_utc_str(self._clock.now()), ref_id),
            )
            journal.append(
                self._conn,
                self._clock,
                employee_id=employee_id,
                type="credential.revoked",
                actor=actor,
                summary=f"credential_ref {ref_id} revoked",
            )
        self._backend.delete(row["backend_locator"])

    @contextmanager
    def use(self, ref_id: str, *, actor: Actor, purpose: str, destination: str) -> Iterator[SecretValue]:
        """Release a secret to the Control Plane broker for one purpose and destination.

        The Runtime, workers and LLM-facing tools are refused: they only ever see ``ref_id``.
        """
        if actor.kind != "control_plane":
            raise VaultError("secrets are released only to the Control Plane broker")
        ref = self.get_ref(ref_id)
        if ref.revoked_at is not None:
            raise VaultError("credential_ref is revoked")
        if ref.expires_at is not None and parse_utc(ref.expires_at) <= self._clock.now():
            raise VaultError("credential_ref is expired")
        if purpose != ref.purpose:
            raise VaultError("purpose not allowed for this credential")
        if not any(fnmatch.fnmatchcase(destination, pat) for pat in ref.allowed_destinations):
            raise VaultError("destination not allowed for this credential")
        locator = self._conn.execute(
            "SELECT backend_locator FROM credential_refs WHERE id = ?", (ref_id,)
        ).fetchone()["backend_locator"]
        raw = self._backend.get(locator)
        if raw is None:
            raise VaultError("secret missing from backend; ask the owner to re-authorize")
        text = raw.decode("utf-8", errors="ignore")
        if len(text) >= 6:
            # Stays registered: log lines emitted after use may still carry the value.
            self._redactor.register(text)
        yield SecretValue(raw)
