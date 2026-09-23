"""THREAT_MODEL T-13: secrets never reach logs or journal text."""

from __future__ import annotations

import pytest

from shared.redaction import REDACTED, Redactor

FAKES = [
    "sk-proj-" + "A" * 32,  # atlas-scan: allow-fake-secret
    "sk-ant-api03-" + "B" * 32,  # atlas-scan: allow-fake-secret
    "AKIA" + "C" * 16,  # atlas-scan: allow-fake-secret
    "ghp_" + "D" * 36,  # atlas-scan: allow-fake-secret
    "Bearer " + "E" * 40,  # atlas-scan: allow-fake-secret
]


@pytest.mark.parametrize("secret", FAKES)
def test_patterns_redacted(secret: str) -> None:
    out = Redactor().redact(f"before {secret} after")
    assert secret not in out
    assert REDACTED in out
    assert out.startswith("before")


def test_key_value_pairs_redacted_keep_key_name() -> None:
    out = Redactor().redact("senha=abc123XYZ token: qwertyuiop")
    assert "abc123XYZ" not in out
    assert "qwertyuiop" not in out
    assert "senha=" in out


def test_registered_exact_values() -> None:
    r = Redactor()
    r.register("valor-opaco-sintetico")
    assert "valor-opaco-sintetico" not in r.redact("x valor-opaco-sintetico y")


def test_short_values_refused() -> None:
    with pytest.raises(ValueError):
        Redactor().register("abc")


def test_private_key_block() -> None:
    block = "-----BEGIN PRIVATE KEY-----\nMIIsynthetic\n-----END PRIVATE KEY-----"  # atlas-scan: allow-fake-secret
    assert "MIIsynthetic" not in Redactor().redact(block)
