"""Egress Guard: the last trusted check before data leaves the machine (A3-02, spec 9.2; T08).

Two independent axes are kept apart (spec 9.1): trust/authority (who may instruct) and sensitivity
(what may be disclosed). This module handles sensitivity only. The decision is taken outside the model
on the classification of the FINAL payload, for a given provider and purpose, reading the consent in
force at that moment (revocation is effective on the next emission):

* SECRET never leaves (credentials are not context);
* SENSITIVE leaves only with a scoped consent ``privacy.sensitive_consents: [{provider, purposes}]``;
* PUBLIC / INTERNAL / PERSONAL go to the provider the owner configured with his own account (BYOK).

Storing a sensitive memory is NOT consent to send it. Unknown classifications are treated as SENSITIVE.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from shared.errors import AtlasError, ErrorCode

LEVELS = ("PUBLIC", "INTERNAL", "PERSONAL", "SENSITIVE", "SECRET")
RANK = {c: i for i, c in enumerate(LEVELS)}


def rank(classification: str) -> int:
    return RANK.get(classification, RANK["SENSITIVE"])  # unknown is never treated as public


def highest(*classifications: str) -> str:
    return max(classifications, key=rank) if classifications else "INTERNAL"


class EgressBlocked(AtlasError):
    def __init__(self, classification: str, provider: str, purpose: str) -> None:
        super().__init__(
            ErrorCode.POLICY_DENIED,
            f"{classification} data may not be sent to {provider} for {purpose} without the owner's consent",
            persisted="nothing sent",
            recommended_action="process locally, remove the sensitive part or ask the owner for a scoped consent",
        )
        self.classification = classification
        self.provider = provider
        self.purpose = purpose


class EgressGuard:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _privacy(self) -> dict[str, Any]:
        row = self.conn.execute("SELECT config_json FROM settings ORDER BY revision DESC LIMIT 1").fetchone()
        if row is None:
            return {}
        privacy: dict[str, Any] = json.loads(row[0]).get("privacy") or {}
        return privacy

    def max_allowed(self, provider: str, purpose: str) -> str:
        """Highest classification that may go to ``provider`` for ``purpose`` right now."""
        for consent in self._privacy().get("sensitive_consents", []):
            if consent.get("provider") == provider and purpose in consent.get("purposes", []):
                return "SENSITIVE"
        return "PERSONAL"

    def check(self, *, provider: str, classification: str, purpose: str) -> None:
        if rank(classification) >= rank("SECRET"):
            raise EgressBlocked("SECRET", provider, purpose)
        if rank(classification) > rank(self.max_allowed(provider, purpose)):
            raise EgressBlocked(classification, provider, purpose)
