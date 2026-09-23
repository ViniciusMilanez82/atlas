"""Secret redaction for logs, journal summaries and diagnostic reports (spec 11.4, 17.1).

Two layers: (1) exact values the Vault registered while a secret was in use; (2) credential-shaped
patterns. Redaction never logs what it removed.
"""

from __future__ import annotations

import logging
import re
import threading

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"\bsk-(?:ant-|proj-|live-|svcacct-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|senha|secret|api[_-]?key|token)\b(\s*[:=]\s*)\S+"),
]


class Redactor:
    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def register(self, value: str) -> None:
        """Register an exact secret value to scrub. Very short values are refused (too noisy)."""
        if len(value) < 6:
            raise ValueError("refusing to register a secret shorter than 6 characters")
        with self._lock:
            self._values.add(value)

    def forget(self, value: str) -> None:
        with self._lock:
            self._values.discard(value)

    def redact(self, text: str) -> str:
        with self._lock:
            values = sorted(self._values, key=len, reverse=True)
        for v in values:
            if v in text:
                text = text.replace(v, REDACTED)
        for pat in _PATTERNS:
            if pat.groups >= 2:
                text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
            else:
                text = pat.sub(REDACTED, text)
        return text


default_redactor = Redactor()


class RedactingFilter(logging.Filter):
    """Logging filter: formats the record, redacts it and freezes the result."""

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or default_redactor

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = self._redactor.redact(message)
        record.args = None
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self._redactor.redact(formatted)
            record.exc_info = None
        return True


def install_on_root_logger(redactor: Redactor | None = None) -> RedactingFilter:
    flt = RedactingFilter(redactor)
    root = logging.getLogger()
    root.addFilter(flt)
    for handler in root.handlers:
        handler.addFilter(flt)
    return flt
