from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/trusted-transition-manifest.yml").read_text(
    encoding="utf-8"
)


class ProofQATrustedReceiptIntegrationTests(unittest.TestCase):
    def test_pull_request_job_has_no_issue_or_oidc_write(self):
        validate = WORKFLOW.split("  validate:", 1)[1].split("\n  produce:", 1)[0]
        self.assertIn("contents: read", validate)
        self.assertNotIn("issues: write", validate)
        self.assertNotIn("id-token: write", validate)

    def test_receipt_is_derived_after_successful_artifact_upload(self):
        produce = WORKFLOW.split("\n  produce:", 1)[1]
        self.assertIn("issues: write", produce)
        self.assertIn("id: upload", produce)
        self.assertIn("steps.upload.outputs.artifact-id", produce)
        self.assertIn("steps.upload.outputs.artifact-url", produce)
        self.assertIn("steps.upload.outputs.artifact-digest", produce)
        self.assertIn("publish_trusted_transition_receipt.py", produce)
        self.assertIn("issue comment 42", produce)
        self.assertLess(
            produce.index("id: upload"),
            produce.index("Publish discoverable receipt ledger entry"),
        )

    def test_receipt_comment_uses_final_audit_and_exact_source_commit(self):
        self.assertIn(
            "--audit artifacts/trusted-transition-reference/final-audit.json",
            WORKFLOW,
        )
        self.assertIn("--source-commit \"$SOURCE_SHA\"", WORKFLOW)
        self.assertIn("--artifact-digest \"$ARTIFACT_DIGEST\"", WORKFLOW)
        self.assertIn("--body-file /tmp/trusted-transition-receipt.md", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
