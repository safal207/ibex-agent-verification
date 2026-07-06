#!/usr/bin/env python3
"""Recompute an expected/observed temporal phase relation vector."""

from __future__ import annotations

import argparse
import json
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

    expected_comparison_id = vector.get("comparison_id")
    if expected_comparison_id and result["comparison_id"] != expected_comparison_id:
        details = {
            "error": "published comparison_id does not recompute",
            "expected": expected_comparison_id,
            "recomputed": result["comparison_id"],
        }
        raise SystemExit(json.dumps(details, sort_keys=True))
    return 0 if result["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
