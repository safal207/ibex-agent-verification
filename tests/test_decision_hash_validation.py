"""Validation boundary tests for decision identifier generation."""

import unittest

from ibex_agent_verification.action_chain import canonical_decision_id


class DecisionHashValidationTests(unittest.TestCase):
    """Ensure malformed records never receive identifiers."""

    def test_empty_record_is_rejected(self):
        """A schema-invalid mapping must fail before canonical hashing."""

        action_id = "sha256:" + "a" * 64
        with self.assertRaises(ValueError):
            canonical_decision_id(action_id, {})


if __name__ == "__main__":
    unittest.main()
