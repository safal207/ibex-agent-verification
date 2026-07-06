#!/usr/bin/env python3
"""Compare the GitHub-declared PR head with the checkout observed by the runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ibex_agent_verification.live_checkout_relation import (
    compare_checkout_materialization,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--actual-head", required=True)
    parser.add_argument("--transition-id", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--clean", choices=("true", "false"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    bundle = compare_checkout_materialization(
        expected_head=args.expected_head,
        actual_head=args.actual_head,
        transition_id=args.transition_id,
        observed_at=args.observed_at,
        clean=args.clean == "true",
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if bundle["comparison"]["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
