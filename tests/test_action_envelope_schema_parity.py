"""Schema parity tests for the ActionEnvelopeV1 identifier surface."""

import unittest

from ibex_agent_verification.action_chain import (
    ACTION_ENVELOPE_OPTIONAL_FIELDS,
    ACTION_ENVELOPE_V1_CONTEXT,
    ACTION_ENVELOPE_V1_REQUIRED_FIELDS,
)
from ibex_agent_verification.schema_validation import load_action_envelope_v1_schema


class ActionEnvelopeSchemaParityTests(unittest.TestCase):
    """Prevent schema and hashing-profile fields from drifting independently."""

    def test_schema_properties_match_locked_hash_surface(self):
        """Every schema property must be bound by the V1 identifier profile."""

        schema = load_action_envelope_v1_schema()
        expected = set(ACTION_ENVELOPE_V1_REQUIRED_FIELDS) | set(
            ACTION_ENVELOPE_OPTIONAL_FIELDS
        )
        self.assertEqual(set(schema["properties"]), expected)
        self.assertEqual(set(schema["required"]), set(ACTION_ENVELOPE_V1_REQUIRED_FIELDS))
        self.assertFalse(schema["additionalProperties"])

    def test_context_constant_matches_schema_identity(self):
        """The self-description URI must be identical in code and schema."""

        schema = load_action_envelope_v1_schema()
        self.assertEqual(schema["$id"], ACTION_ENVELOPE_V1_CONTEXT)
        self.assertEqual(
            schema["properties"]["@context"]["const"],
            ACTION_ENVELOPE_V1_CONTEXT,
        )


if __name__ == "__main__":
    unittest.main()
