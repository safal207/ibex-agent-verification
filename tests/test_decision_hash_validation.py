"""Validation boundary tests for decision identifier generation."""

import json
import unittest
from pathlib import Path

from ibex_agent_verification.action_chain import canonical_decision_id

VECTOR = (
    Path(__file__).resolve().parents[1]
    / "conformance"
    / "verifiable-action-chain-v1.json"
)


class DecisionHashValidationTests(unittest.TestCase):
    """Ensure malformed records never receive identifiers."""

    def test_empty_record_is_rejected(self):
        """A schema-invalid mapping must fail before canonical hashing."""

        action_id = "sha256:" + "a" * 64
        with self.assertRaises(ValueError):
            canonical_decision_id(action_id, {})

    def test_non_finite_excluded_metrics_are_rejected(self):
        """Excluded cost metadata must still remain valid JSON before hashing."""

        vector = json.loads(VECTOR.read_text(encoding="utf-8"))
        action_id = vector["action"]["id"]
        baseline = vector["decision"]["source_record"]

        for amount in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(amount=amount):
                record = dict(
                    baseline,
                    estimated_cost_avoided={
                        "amount": amount,
                        "currency": "USD",
                        "method": "estimate",
                    },
                )
                with self.assertRaisesRegex(ValueError, "schema validation failed"):
                    canonical_decision_id(action_id, record)


if __name__ == "__main__":
    unittest.main()
