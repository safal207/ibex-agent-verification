import json
import unittest

from scripts.publish_trusted_artifact_ingestion_receipt import (
    IngestionReceiptError,
    render_receipt,
)


REPOSITORY = "safal207/ibex-agent-verification"
COMMIT = "a" * 40
PRODUCER_RUN_ID = 222222222
SOURCE_RUN_ID = 111111111
FINAL_ARTIFACT_ID = 333333333
FINAL_URL = (
    f"https://github.com/{REPOSITORY}/actions/runs/"
    f"{PRODUCER_RUN_ID}/artifacts/{FINAL_ARTIFACT_ID}"
)
CLAIM = (
    "This signed reference bundle verifies trusted cross-workflow artifact ingestion "
    "and manifest signing. It is not a production deployment claim."
)


def audit():
    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "repository": REPOSITORY,
        "source_commit": COMMIT,
        "manifest_sha256": "1" * 64,
        "receipt_sha256": "2" * 64,
        "gate_report_sha256": "3" * 64,
        "sigstore_bundle_sha256": "4" * 64,
        "claim_boundary": CLAIM,
        "source_artifact": {
            "id": 444444444,
            "name": f"proofqa-transition-source-{COMMIT}",
            "digest": "sha256:" + "5" * 64,
            "run_id": SOURCE_RUN_ID,
            "run_attempt": 2,
        },
    }


def render(payload=None, **overrides):
    arguments = {
        "audit": audit() if payload is None else payload,
        "repository": REPOSITORY,
        "source_commit": COMMIT,
        "producer_run_id": str(PRODUCER_RUN_ID),
        "source_run_id": str(SOURCE_RUN_ID),
        "final_artifact_id": str(FINAL_ARTIFACT_ID),
        "final_artifact_url": FINAL_URL,
        "final_artifact_digest": "sha256:" + "6" * 64,
    }
    arguments.update(overrides)
    return render_receipt(**arguments)


class TrustedArtifactIngestionReceiptTests(unittest.TestCase):
    def test_receipt_binds_source_and_final_artifacts(self):
        body = render()
        payload = json.loads(body.split("```json\n", 1)[1].split("\n```", 1)[0])

        self.assertEqual(
            payload["type"],
            "trusted-transition-artifact-ingestion-receipt",
        )
        self.assertEqual(payload["source_commit"], COMMIT)
        self.assertEqual(payload["source_run_id"], SOURCE_RUN_ID)
        self.assertEqual(payload["source_run_attempt"], 2)
        self.assertEqual(payload["producer_run_id"], PRODUCER_RUN_ID)
        self.assertEqual(payload["final_artifact"]["id"], FINAL_ARTIFACT_ID)
        self.assertEqual(
            payload["source_artifact"]["name"],
            f"proofqa-transition-source-{COMMIT}",
        )
        self.assertEqual(payload["attestation_status"], "VERIFIED")
        self.assertEqual(payload["gate_decision"], "PASS")

    def test_source_run_mismatch_is_rejected(self):
        with self.assertRaisesRegex(
            IngestionReceiptError,
            "source workflow run mismatch",
        ):
            render(source_run_id="999999999")

    def test_foreign_final_artifact_url_is_rejected(self):
        with self.assertRaisesRegex(
            IngestionReceiptError,
            "final artifact URL identity mismatch",
        ):
            render(
                final_artifact_url=(
                    "https://github.com/foreign/repository/actions/runs/"
                    f"{PRODUCER_RUN_ID}/artifacts/{FINAL_ARTIFACT_ID}"
                )
            )

    def test_source_artifact_name_must_bind_commit(self):
        payload = audit()
        payload["source_artifact"]["name"] = "proofqa-transition-source-other"

        with self.assertRaisesRegex(
            IngestionReceiptError,
            "does not bind the commit",
        ):
            render(payload)

    def test_broad_claim_boundary_is_rejected(self):
        payload = audit()
        payload["claim_boundary"] = "This proves production deployment correctness."

        with self.assertRaisesRegex(
            IngestionReceiptError,
            "claim boundary",
        ):
            render(payload)


if __name__ == "__main__":
    unittest.main()
