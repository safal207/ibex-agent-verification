import json
import unittest

from scripts.publish_trusted_transition_receipt import TrustedReceiptError, render_receipt


REPOSITORY = "safal207/ibex-agent-verification"
COMMIT = "a" * 40


def audit():
    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "repository": REPOSITORY,
        "source_commit": COMMIT,
        "manifest_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "gate_report_sha256": "d" * 64,
        "sigstore_bundle_sha256": "e" * 64,
        "claim_boundary": (
            "This signed reference bundle verifies the trusted post-CI producer path. "
            "It is not a production deployment claim."
        ),
    }


def render(value=None, artifact_url=None):
    return render_receipt(
        audit=value or audit(),
        repository=REPOSITORY,
        source_commit=COMMIT,
        producer_run_id="123",
        trigger_run_id="122",
        artifact_id="456",
        artifact_url=artifact_url or (
            "https://github.com/safal207/ibex-agent-verification/"
            "actions/runs/123/artifacts/456"
        ),
        artifact_digest="sha256:" + "f" * 64,
    )


class TrustedReceiptTests(unittest.TestCase):
    def test_valid_body_contains_stable_json_receipt(self):
        body = render()
        payload_text = body.split("```json\n", 1)[1].split("\n```", 1)[0]
        payload = json.loads(payload_text)
        self.assertEqual(payload["source_commit"], COMMIT)
        self.assertEqual(payload["artifact"]["id"], 456)
        self.assertEqual(payload["attestation_status"], "VERIFIED")
        self.assertEqual(payload["gate_decision"], "PASS")

    def test_foreign_artifact_url_is_rejected(self):
        with self.assertRaisesRegex(TrustedReceiptError, "artifact URL"):
            render(artifact_url="https://github.com/other/repo/actions/runs/123/artifacts/456")

    def test_broadened_claim_is_rejected(self):
        value = audit()
        value["claim_boundary"] = "Production deployment verified."
        with self.assertRaisesRegex(TrustedReceiptError, "claim boundary"):
            render(value=value)


if __name__ == "__main__":
    unittest.main()
