"""Repository secret scanner (AT-001: no credentials or real data in history).

Scans tracked + untracked-not-ignored files (or paths passed as arguments) for credential
patterns. Exit code 1 when anything is found. Findings print file and line only, never the
matched value.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_key": re.compile(r"\bsk-(?:proj-|live-|svcacct-)?[A-Za-z0-9_-]{20,}"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY"),
    "generic_assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"
    ),
    "cpf": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
}

SKIP_SUFFIXES = {".docx", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip"}
# The received specification is preserved verbatim and scanned separately by review.
SKIP_PATHS = {"docs/spec", "docs/MASTER_SPEC.md"}
# Test files may contain deliberately fake secrets for redaction tests, marked inline.
ALLOW_MARKER = "atlas-scan: allow-fake-secret"


def candidate_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def skipped(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return path.suffix.lower() in SKIP_SUFFIXES or any(
        rel == s or rel.startswith(s + "/") for s in SKIP_PATHS
    )


def scan(paths: list[Path]) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in paths:
        if not path.is_file() or skipped(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if ALLOW_MARKER in line:
                continue
            for name, pat in PATTERNS.items():
                if pat.search(line):
                    findings.append((path.relative_to(ROOT).as_posix(), lineno, name))
    return findings


def main(argv: list[str]) -> int:
    paths = [Path(a).resolve() for a in argv] if argv else candidate_files()
    findings = scan(paths)
    for rel, lineno, name in findings:
        print(f"{rel}:{lineno}: possible {name}")
    print(f"secret scan: {len(findings)} finding(s) in {len(paths)} file(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
