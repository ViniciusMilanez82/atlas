"""Owner-run 'Testar inteligência': ONE small, billable call under an explicit ceiling.

Usage (the key is read from ATLAS_OPENAI_API_KEY or typed locally without echo; never paste it in chat):

    python scripts/intelligence_check.py --model gpt-6-sol --max-cost-cents 5 [--evidence out.json]

Prints a JSON report without the prompt or the key. Exit code 0 only when the check passed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.models.intelligence_check import run_intelligence_check
from security.vault.vault import SecretValue


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="exact API model id, e.g. gpt-6-sol")
    ap.add_argument(
        "--max-cost-cents", type=int, required=True, help="hard ceiling for this check, in USD cents"
    )
    ap.add_argument("--evidence", type=Path, help="write the JSON report here")
    args = ap.parse_args()
    key = os.environ.get("ATLAS_OPENAI_API_KEY") or getpass.getpass("OpenAI API key (not echoed): ")
    if not key:
        print("no key provided", file=sys.stderr)
        return 2
    secret = key.encode()
    report = run_intelligence_check(
        key_provider=lambda: SecretValue(secret), model_id=args.model, max_cost_minor=args.max_cost_cents
    )
    text = report.to_json()
    print(text)
    if args.evidence:
        args.evidence.write_text(text, encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
