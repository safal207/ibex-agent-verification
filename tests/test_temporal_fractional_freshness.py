from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from ibex_agent_verification.temporal_phase_relations import (
    STALE_EVIDENCE,
    compare_expected_to_observed,
)

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / "qa/temporal-phase-relation-vector.json"


class FractionalEvidenceFreshnessTests(unittest.TestCase):
    def test_fraction_past_freshness_window_fails_closed(self) -> None:
        vector = json.loads(VECTOR.read_text(encoding="utf-8"))
        expected = copy.deepcopy(vector["expected"])
        observed = copy.deepcopy(vector["observed"])
        expected["evidence_max_age_seconds"] = 5
        observed["observed_at"] = "2026-07-05T10:30:00.900000Z"
        observed["evidence_refs"][0]["captured_at"] = (
            "2026-07-05T10:29:55.000000Z"
        )

        result = compare_expected_to_observed(expected, observed)

        self.assertEqual(result["status"], STALE_EVIDENCE)
        self.assertEqual(result["mismatches"][0]["age_seconds"], 6)
        self.assertEqual(result["mismatches"][0]["max_age_seconds"], 5)


if __name__ == "__main__":
    unittest.main()
