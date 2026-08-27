"""Optional-authority binding tests for decision identifiers."""

import json
import unittest
from pathlib import Path

from ibex_agent_verification.action_chain import canonical_decision_id

VECTOR = Path(__file__).resolve().parents[1] / "conformance" / "verifiable-action-chain-v1.json"


class OptionalAuthorityBindingTests(unittest.TestCase):
    """Ensure optional authority fields participate in the digest."""

    def test_retry_policy_changes_identifier(self):
        """Changing retry policy must change the decision identifier."""

        vector = json.loads(VECTOR.read_text(encoding="utf-8"))
        action_id = vector["action"]["id"]
        baseline_record = vector["decision"]["source_record"]
        changed_record = dict(baseline_record, retry_policy="AFTER_APPROVAL")
        self.assertNotEqual(
            canonical_decision_id(action_id, baseline_record),
            canonical_decision_id(action_id, changed_record),
        )


if __name__ == "__main__":
    unittest.main()
