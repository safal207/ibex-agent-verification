from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / ".github/workflows/proofqa-transition-source.yml").read_text(encoding="utf-8")
TRUSTED = (ROOT / ".github/workflows/trusted-transition-artifact.yml").read_text(encoding="utf-8")


class TrustedTransitionArtifactWorkflowTests(unittest.TestCase):
    def test_source_precedes_upload(self):
        build = SOURCE.index("python scripts/trusted_transition_reference_source.py")
        validate = SOURCE.index("python scripts/production_transition_source.py")
        upload = SOURCE.index("name: Upload exact reference source")
        self.assertLess(build, validate)
        self.assertLess(validate, upload)

    def test_ingestion_precedes_manifest(self):
        extract = TRUSTED.index("python scripts/trusted_transition_artifact.py extract")
        validate = TRUSTED.index("python scripts/production_transition_source.py")
        manifest = TRUSTED.index("python scripts/proofqa_transition_manifest_builder.py")
        self.assertLess(extract, validate)
        self.assertLess(validate, manifest)

    def test_workflow_names_are_exact(self):
        self.assertIn("ProofQA Release Gate Action", SOURCE)
        self.assertIn("ProofQA Transition Source Artifact", TRUSTED)

    def test_pull_request_validation_cannot_publish_receipts(self):
        validate = TRUSTED.split("  validate:", 1)[1].split("\n  produce:", 1)[0]
        self.assertIn("contents: read", validate)
        self.assertNotIn("issues: write", validate)
        self.assertNotIn("id-token", validate)
        self.assertNotIn("gh issue comment", validate)

    def test_receipt_publication_follows_upload_and_audit(self):
        audit = TRUSTED.index("name: Audit final cross-workflow trust chain")
        upload = TRUSTED.index("name: Upload signed ingested trust chain")
        publish = TRUSTED.index("name: Publish artifact-ingestion receipt")
        self.assertLess(audit, upload)
        self.assertLess(upload, publish)
        self.assertIn("issues: write", TRUSTED)
        self.assertIn("steps.upload-trust-chain.outputs.artifact-id", TRUSTED)
        self.assertIn("steps.upload-trust-chain.outputs.artifact-url", TRUSTED)
        self.assertIn("steps.upload-trust-chain.outputs.artifact-digest", TRUSTED)
        self.assertIn("publish_trusted_artifact_ingestion_receipt.py", TRUSTED)
        self.assertIn("gh issue comment 42", TRUSTED)


if __name__ == "__main__":
    unittest.main()
