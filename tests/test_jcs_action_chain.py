"""Conformance tests for canonical JSON and verifiable action-chain identifiers."""

import unittest

from ibex_agent_verification.action_chain import (
    canonical_action_id,
    canonical_chain_record_id,
    canonical_decision_id,
    continuation_matches,
)
from ibex_agent_verification.canonical_json import (
    CanonicalizationError,
    canonicalize_jcs,
    sha256_jcs,
)


def envelope(**overrides):
    """Build one valid frozen action-envelope fixture."""

    value = {
        "tool_identity": "send_email",
        "args_digest": "sha256:" + "a" * 64,
        "caller_identity": "agent:qa",
        "resource_scope": "workspace:demo",
        "policy_version": "policy-v1",
    }
    value.update(overrides)
    return value


def decision(**overrides):
    """Build one valid decision-authority fixture."""

    value = {
        "schema_version": 1,
        "decision_id": "placeholder",
        "tool_call_id": "tc-1",
        "label": "test",
        "decision": "REPAIR",
        "reason_code": "TEST",
        "policy_version": "policy-v1",
        "verifier_depth": "D2",
        "allowed_runtime_use": ["STRUCTURED_REPLAN", "AUDIT_LOG"],
        "trust_domain": "tenant:demo",
        "claim_ceiling": "bounded",
        "permitted_next_transition": "REPLAN",
        "evidence_refs": ["sha256:" + "b" * 64, "sha256:" + "c" * 64],
        "issued_at": "2026-06-30T12:00:00Z",
    }
    value.update(overrides)
    return value


class JCSActionChainTests(unittest.TestCase):
    """Verify deterministic identifiers and fail-closed malformed-input behavior."""

    def test_jcs_orders_keys_by_utf16_code_units(self):
        """JCS must use UTF-16 code-unit ordering rather than Unicode code points."""

        self.assertEqual(
            canonicalize_jcs({"\ue000": 1, "\U00010000": 2}).decode(),
            '{"𐀀":2,"\ue000":1}',
        )

    def test_jcs_rejects_floats_and_unsafe_integers(self):
        """The restricted numeric profile must reject ambiguous numbers."""

        with self.assertRaises(CanonicalizationError):
            canonicalize_jcs({"value": 1.5})
        with self.assertRaises(CanonicalizationError):
            canonicalize_jcs({"value": 9_007_199_254_740_992})

    def test_action_id_matches_published_conformance_vector(self):
        """The published action preimage must recompute byte-for-byte."""

        self.assertEqual(
            canonical_action_id(envelope()),
            (
                "sha256:5efc8759c0a4fb5ab9b33a1a0d8b9ca"
                "69d123eaac8d6c643e7a271906ce1b11d"
            ),
        )

    def test_action_id_is_stable_and_rejects_unbound_fields(self):
        """Mapping order is irrelevant while unknown envelope fields fail closed."""

        left = envelope()
        right = dict(reversed(list(left.items())))
        self.assertEqual(canonical_action_id(left), canonical_action_id(right))
        with self.assertRaises(ValueError):
            canonical_action_id({**left, "unbound": "drift"})

    def test_authorization_deadline_is_bound_when_present(self):
        """A frozen authorization deadline must change the action identifier."""

        plain = canonical_action_id(envelope())
        bounded = canonical_action_id(
            envelope(authorization_deadline="2026-07-01T00:00:00Z")
        )
        self.assertNotEqual(plain, bounded)

    def test_continuation_fails_closed_for_malformed_envelope(self):
        """Malformed or drifted resume inputs must return false rather than escape."""

        frozen = canonical_action_id(envelope())
        self.assertFalse(continuation_matches(frozen, {**envelope(), "extra": "drift"}))
        self.assertFalse(continuation_matches("bad", envelope()))

    def test_decision_id_rejects_non_mapping_before_field_access(self):
        """Malformed decisions must raise the typed mapping error, not AttributeError."""

        action_id = canonical_action_id(envelope())
        with self.assertRaisesRegex(TypeError, "guardrail decision must be a mapping"):
            canonical_decision_id(action_id, None)  # type: ignore[arg-type]

    def test_decision_id_normalizes_semantic_sets(self):
        """Order-independent authority sets must produce the same decision ID."""

        action_id = canonical_action_id(envelope())
        left = decision()
        right = decision(
            allowed_runtime_use=list(reversed(left["allowed_runtime_use"])),
            evidence_refs=list(reversed(left["evidence_refs"])),
        )
        self.assertEqual(
            canonical_decision_id(action_id, left),
            canonical_decision_id(action_id, right),
        )

    def test_decision_id_changes_with_authority_or_evidence(self):
        """Changing authority or evidence must change the bound decision ID."""

        action_id = canonical_action_id(envelope())
        baseline = canonical_decision_id(action_id, decision())
        self.assertNotEqual(
            baseline,
            canonical_decision_id(
                action_id,
                decision(permitted_next_transition="AUDIT_ONLY"),
            ),
        )
        self.assertNotEqual(
            baseline,
            canonical_decision_id(
                action_id,
                decision(evidence_refs=["sha256:" + "d" * 64]),
            ),
        )

    def test_chain_record_binds_upstream_and_payload(self):
        """A link identifier must bind record type, upstream ID, and payload."""

        upstream = sha256_jcs({"decision": "allow"})
        payload = sha256_jcs({"outcome": "done"})
        first = canonical_chain_record_id("execution_outcome", upstream, payload)
        self.assertNotEqual(
            first,
            canonical_chain_record_id("audit_record", upstream, payload),
        )
        self.assertNotEqual(
            first,
            canonical_chain_record_id(
                "execution_outcome",
                sha256_jcs({"decision": "deny"}),
                payload,
            ),
        )


if __name__ == "__main__":
    unittest.main()
