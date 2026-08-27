"""Conformance tests for the self-describing ActionEnvelopeV1 profile."""

import json
import unittest
from pathlib import Path

from ibex_agent_verification.action_chain import (
    ACTION_ENVELOPE_V1_CONTEXT,
    canonical_action_envelope_v1_id,
    canonical_action_id,
    continuation_matches,
)
from ibex_agent_verification.canonical_json import canonicalize_jcs
from ibex_agent_verification.schema_validation import (
    load_action_envelope_v1_schema,
    validate_action_envelope_v1,
)
from ibex_agent_verification.verifier_depth import (
    canonical_action_id as verifier_depth_action_id,
    continuation_matches as verifier_depth_continuation_matches,
)

VECTOR = (
    Path(__file__).resolve().parents[1]
    / "conformance"
    / "action-envelope-v1.json"
)


class ActionEnvelopeV1Tests(unittest.TestCase):
    """Verify the schema, canonical bytes, migration path, and resume invariant."""

    def setUp(self):
        """Load a fresh copy of the published vector for each test."""

        self.vector = json.loads(VECTOR.read_text(encoding="utf-8"))
        self.envelope = self.vector["preimage"]

    def test_schema_and_context_are_self_describing(self):
        """The executable schema and every vector context must be identical."""

        schema = load_action_envelope_v1_schema()
        self.assertEqual(schema["$id"], ACTION_ENVELOPE_V1_CONTEXT)
        self.assertEqual(self.vector["schema"], ACTION_ENVELOPE_V1_CONTEXT)
        self.assertEqual(
            self.vector["schema"],
            self.envelope["@context"],
        )
        self.assertEqual(validate_action_envelope_v1(self.envelope), ())

    def test_published_vector_recomputes_byte_for_byte(self):
        """Independent builders must reproduce the exact canonical bytes and ID."""

        self.assertEqual(
            canonicalize_jcs(self.envelope).decode(),
            self.vector["canonical_utf8"],
        )
        self.assertEqual(
            canonical_action_envelope_v1_id(self.envelope),
            self.vector["id"],
        )
        self.assertEqual(canonical_action_id(self.envelope), self.vector["id"])
        self.assertEqual(verifier_depth_action_id(self.envelope), self.vector["id"])

    def test_missing_or_wrong_context_fails_strict_profile(self):
        """V1 cannot silently downgrade or switch schema semantics."""

        missing = dict(self.envelope)
        missing.pop("@context")
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            canonical_action_envelope_v1_id(missing)

        wrong = dict(self.envelope, **{"@context": "urn:example:other"})
        with self.assertRaisesRegex(ValueError, "expected constant"):
            canonical_action_envelope_v1_id(wrong)

    def test_noncanonical_namespaces_and_timestamps_fail(self):
        """Cross-builder identity and deadline spellings are rejection profiles."""

        upper_identity = dict(self.envelope, caller_identity="Agent:QA")
        with self.assertRaisesRegex(ValueError, "required pattern"):
            canonical_action_envelope_v1_id(upper_identity)

        offset_deadline = dict(
            self.envelope,
            authorization_deadline="2026-07-01T08:00:00+03:00",
        )
        with self.assertRaisesRegex(ValueError, "required pattern"):
            canonical_action_envelope_v1_id(offset_deadline)

        fractional_deadline = dict(
            self.envelope,
            authorization_deadline="2026-07-01T05:00:00.000Z",
        )
        with self.assertRaisesRegex(ValueError, "required pattern"):
            canonical_action_envelope_v1_id(fractional_deadline)

    def test_unknown_fields_and_context_drift_fail_closed(self):
        """Unbound fields or a changed profile must never resume an action."""

        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            canonical_action_envelope_v1_id({**self.envelope, "unbound": "drift"})

        frozen = canonical_action_envelope_v1_id(self.envelope)
        changed = dict(self.envelope, **{"@context": "urn:example:other"})
        self.assertFalse(continuation_matches(frozen, changed))
        self.assertFalse(verifier_depth_continuation_matches(frozen, changed))

    def test_original_unversioned_vector_remains_compatible(self):
        """The new strict profile must not invalidate the published legacy vector."""

        legacy = {
            "tool_identity": "send_email",
            "args_digest": "sha256:" + "a" * 64,
            "caller_identity": "agent:qa",
            "resource_scope": "workspace:demo",
            "policy_version": "policy-v1",
        }
        expected = (
            "sha256:5efc8759c0a4fb5ab9b33a1a0d8b9ca"
            "69d123eaac8d6c643e7a271906ce1b11d"
        )
        self.assertEqual(canonical_action_id(legacy), expected)
        self.assertEqual(verifier_depth_action_id(legacy), expected)


if __name__ == "__main__":
    unittest.main()
