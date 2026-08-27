#!/usr/bin/env python3
"""Evaluate an exact-head binding GitHub human-review gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ibex_agent_verification.human_review_receipts import (
    evaluate_human_review_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--head", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--reviews", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args()

    try:
        reviews = json.loads(Path(args.reviews).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reviews = None

    gate = evaluate_human_review_gate(
        repository=args.repository,
        pull_request_number=args.pull_request,
        current_head=args.head,
        author=args.author,
        reviews=reviews,
        observed_at=args.observed_at,
        policy_version=args.policy_version,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"status={gate['status']}\n")
            handle.write(
                f"gate_satisfied={str(gate['gate_satisfied']).lower()}\n"
            )
            handle.write(f"gate_record_id={gate['gate_record_id']}\n")

    return 1 if gate["status"] == "NON_RECOMPUTABLE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
