"""IPC sessions: the only source of the caller's identity (spec 13.4; review R-05).

The Supervisor issues a random token per client process (local app, paired-device bridge, runtime)
and hands it over out of band (e.g. a 0600 file or the launch environment). Only the SHA-256 of the
token is kept. The actor of every request is derived from the session; a request body can never
declare its own actor or role.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass

from shared.actors import Actor

ALLOWED_KINDS = {"owner", "device", "runtime"}


@dataclass(frozen=True)
class Session:
    actor: Actor
    employee_id: str


class SessionRegistry:
    def __init__(self) -> None:
        self._by_hash: dict[str, Session] = {}
        self._lock = threading.Lock()

    def issue(self, actor: Actor, employee_id: str) -> str:
        if actor.kind not in ALLOWED_KINDS:
            raise ValueError(f"sessions cannot be issued to {actor.kind}")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._by_hash[hashlib.sha256(token.encode()).hexdigest()] = Session(actor, employee_id)
        return token

    def resolve(self, token: object) -> Session | None:
        if not isinstance(token, str) or len(token) > 256:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            for known, session in self._by_hash.items():
                if hmac.compare_digest(known, digest):
                    return session
        return None

    def revoke_actor(self, actor_id: str) -> int:
        with self._lock:
            dead = [h for h, s in self._by_hash.items() if s.actor.id == actor_id]
            for h in dead:
                del self._by_hash[h]
        return len(dead)
