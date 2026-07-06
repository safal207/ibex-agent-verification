#!/usr/bin/env python3
"""Recompute an expected/observed temporal phase relation vector."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ibex_agent_verification.temporal_phase_relations import compare_expected_to_observed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    vector = json.loads(Path(args.vector).read_text(encoding="utf-8"))
    result = compare_expected_to_observed(vector["expected"], vector.get("observed"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    expected_id = vector.get("comparison_id")
    if expected_id and result["comparison_id"] != expected_id:
        print(
            json.dumps(
                {
                    "error": "published comparison_id does not recompute",
                    "expected": expected_id,
                    "recomputed": result["comparison_id"],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    return 0 if result["status"] == "MATCH" else 1


if __name__ == "__main__":
    sys.exit(main())
