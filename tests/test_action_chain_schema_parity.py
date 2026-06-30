"""Schema parity tests for decision identifier field classification."""

import unittest

from ibex_agent_verification.action_chain import (
    DECISION_BOUND_AUDIT_FIELDS,
    DECISION_BOUND_AUTHORITY_FIELDS,
    DECISION_EXPLICITLY_EXCLUDED_FIELDS,
)
from ibex_agent_verification.schema_validation import load_guardrail_decision_schema


class DecisionSchemaParityTests(unittest.TestCase):
    """Require every decision-schema property to have one binding policy."""

    def test_schema_fields_are_classified_exactly_once(self):
        """Fail when a schema property is unclassified or multiply classified."""

        schema_fields = set(load_guardrail_decision_schema()["properties"])
        classified = (
            *DECISION_BOUND_AUTHORITY_FIELDS,
            *DECISION_BOUND_AUDIT_FIELDS,
            *DECISION_EXPLICITLY_EXCLUDED_FIELDS,
        )
        self.assertEqual(len(classified), len(set(classified)))
        self.assertEqual(schema_fields, set(classified))


if __name__ == "__main__":
    unittest.main()
