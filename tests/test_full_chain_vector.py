"""Byte-for-byte tests for the published verifiable action-chain vector."""

import json
import unittest
from pathlib import Path

from ibex_agent_verification.action_chain import (
    canonical_action_id,
    canonical_chain_record_id,
    canonical_decision_id,
)
from ibex_agent_verification.canonical_json import canonicalize_jcs, sha256_jcs

VECTOR = (
    Path(__file__).resolve().parents[1]
    / "conformance"
    / "verifiable-action-chain-v1.json"
)


class FullChainVectorTests(unittest.TestCase):
    """Recompute every published canonical byte string and identifier."""

    def test_full_chain_recomputes(self):
        """Action, decision, outcome, and audit links must all match the vector."""

        vector = json.loads(VECTOR.read_text(encoding="utf-8"))
        action = vector["action"]
        self.assertEqual(
            canonicalize_jcs(action["preimage"]).decode(),
            action["canonical_utf8"],
        )
        self.assertEqual(canonical_action_id(action["preimage"]), action["id"])

        decision = vector["decision"]
        decision_preimage = json.loads(decision["canonical_preimage_utf8"])
        self.assertEqual(
            canonicalize_jcs(decision_preimage).decode(),
            decision["canonical_preimage_utf8"],
        )
        self.assertEqual(sha256_jcs(decision_preimage), decision["id"])
        self.assertEqual(
            canonical_decision_id(action["id"], decision["source_record"]),
            decision["id"],
        )

        outcome = vector["execution_outcome"]
        self.assertEqual(
            canonicalize_jcs(outcome["payload"]).decode(),
            outcome["payload_canonical_utf8"],
        )
        self.assertEqual(sha256_jcs(outcome["payload"]), outcome["payload_ref"])
        outcome_link = json.loads(outcome["link_canonical_utf8"])
        self.assertEqual(
            canonicalize_jcs(outcome_link).decode(),
            outcome["link_canonical_utf8"],
        )
        self.assertEqual(sha256_jcs(outcome_link), outcome["id"])
        self.assertEqual(
            canonical_chain_record_id(
                "execution_outcome",
                decision["id"],
                outcome["payload_ref"],
            ),
            outcome["id"],
        )

        audit = vector["audit_record"]
        self.assertEqual(
            canonicalize_jcs(audit["payload"]).decode(),
            audit["payload_canonical_utf8"],
        )
        self.assertEqual(sha256_jcs(audit["payload"]), audit["payload_ref"])
        audit_link = json.loads(audit["link_canonical_utf8"])
        self.assertEqual(
            canonicalize_jcs(audit_link).decode(),
            audit["link_canonical_utf8"],
        )
        self.assertEqual(sha256_jcs(audit_link), audit["id"])
        self.assertEqual(
            canonical_chain_record_id(
                "audit_record",
                outcome["id"],
                audit["payload_ref"],
            ),
            audit["id"],
        )


if __name__ == "__main__":
    unittest.main()
