from __future__ import annotations

import unittest

from ibex_agent_verification.live_checkout_relation import (
    compare_checkout_materialization,
)
from ibex_agent_verification.temporal_phase_relations import (
    IDENTITY_MISMATCH,
    MATCH,
    OUTCOME_DEVIATION,
)

HEAD = "a" * 40
OBSERVED_AT = "2026-07-05T17:50:00Z"


class LiveCheckoutRelationTests(unittest.TestCase):
    def test_exact_clean_checkout_matches_without_authorizing(self) -> None:
        bundle = compare_checkout_materialization(
            expected_head=HEAD,
            actual_head=HEAD,
            transition_id="workflow-run:1:verify",
            observed_at=OBSERVED_AT,
            clean=True,
        )
        comparison = bundle["comparison"]
        self.assertEqual(comparison["status"], MATCH)
        self.assertTrue(comparison["transition_supported"])
        self.assertFalse(comparison["transition_authorized"])

    def test_different_actual_head_is_identity_mismatch(self) -> None:
        bundle = compare_checkout_materialization(
            expected_head=HEAD,
            actual_head="b" * 40,
            transition_id="workflow-run:1:verify",
            observed_at=OBSERVED_AT,
            clean=True,
        )
        self.assertEqual(bundle["comparison"]["status"], IDENTITY_MISMATCH)

    def test_dirty_checkout_is_outcome_deviation(self) -> None:
        bundle = compare_checkout_materialization(
            expected_head=HEAD,
            actual_head=HEAD,
            transition_id="workflow-run:1:verify",
            observed_at=OBSERVED_AT,
            clean=False,
        )
        self.assertEqual(bundle["comparison"]["status"], OUTCOME_DEVIATION)

    def test_invalid_head_is_rejected_before_comparison(self) -> None:
        with self.assertRaises(ValueError):
            compare_checkout_materialization(
                expected_head="main",
                actual_head=HEAD,
                transition_id="workflow-run:1:verify",
                observed_at=OBSERVED_AT,
                clean=True,
            )


if __name__ == "__main__":
    unittest.main()
