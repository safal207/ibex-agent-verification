from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SOURCE = (
    ROOT / ".github/workflows/proofqa-transition-source.yml"
).read_text(encoding="utf-8")
PROMOTION = (
    ROOT / ".github/workflows/ibex-evidence-promotion.yml"
).read_text(encoding="utf-8")
TRUSTED = (
    ROOT / ".github/workflows/trusted-transition-artifact.yml"
).read_text(encoding="utf-8")


class TrustedTransitionArtifactWorkflowTests(unittest.TestCase):
    def test_reference_source_remains_reproducible_and_read_only(self):
        build = REFERENCE_SOURCE.index(
            "python scripts/trusted_transition_reference_source.py"
        )
        validate = REFERENCE_SOURCE.index(
            "python scripts/production_transition_source.py"
        )
        upload = REFERENCE_SOURCE.index("name: Upload exact reference source")
        self.assertLess(build, validate)
        self.assertLess(validate, upload)
        self.assertNotIn("id-token", REFERENCE_SOURCE)
        self.assertNotIn("actions/attest", REFERENCE_SOURCE)

    def test_real_promotion_requires_exact_successful_e2e_run(self):
        self.assertIn('workflows: ["Ibex Verilator E2E"]', PROMOTION)
        self.assertIn("workflow_run.conclusion == 'success'", PROMOTION)
        self.assertIn("workflow_run.event == 'push'", PROMOTION)
        self.assertIn("workflow_run.head_branch == 'main'", PROMOTION)
        self.assertIn(
            "workflow_run.head_repository.full_name == github.repository",
            PROMOTION,
        )
        self.assertIn("environment: ibex-evidence-release", PROMOTION)
        self.assertNotIn("id-token", PROMOTION)
        self.assertNotIn("actions/attest", PROMOTION)

    def test_promotion_validates_raw_evidence_before_source_upload(self):
        select = PROMOTION.index("name: Select exact Ibex E2E artifact")
        download = PROMOTION.index("name: Download raw Ibex evidence archive")
        promote = PROMOTION.index("python scripts/ibex_evidence_promotion.py")
        verify = PROMOTION.index("ibex-av verify-evidence")
        source_validate = PROMOTION.index(
            "python scripts/production_transition_source.py"
        )
        upload = PROMOTION.index("name: Upload exact production transition source")
        self.assertLess(select, download)
        self.assertLess(download, promote)
        self.assertLess(promote, verify)
        self.assertLess(verify, source_validate)
        self.assertLess(source_validate, upload)
        self.assertIn("skip-decompress: true", PROMOTION)
        self.assertIn("digest-mismatch: error", PROMOTION)
        self.assertIn("--expected-workflow .github/workflows/ibex-e2e.yml", PROMOTION)
        self.assertIn("--expected-ibex-ref", PROMOTION)

    def test_trusted_ingestion_only_accepts_promotion_workflow(self):
        self.assertIn('workflows: ["Ibex Evidence Promotion"]', TRUSTED)
        self.assertIn(
            "SOURCE_WORKFLOW: .github/workflows/ibex-evidence-promotion.yml",
            TRUSTED,
        )
        self.assertIn("DESTINATION_ENVIRONMENT: ibex-evidence-release", TRUSTED)
        self.assertIn("--expected-source-workflow \"$SOURCE_WORKFLOW\"", TRUSTED)
        self.assertNotIn(
            'workflows: ["ProofQA Transition Source Artifact"]',
            TRUSTED,
        )

    def test_ingestion_precedes_manifest_and_attestation(self):
        extract = TRUSTED.index("python scripts/trusted_transition_artifact.py extract")
        validate = TRUSTED.index("python scripts/production_transition_source.py")
        manifest = TRUSTED.index("python scripts/proofqa_transition_manifest_builder.py")
        attest = TRUSTED.index("uses: actions/attest@")
        self.assertLess(extract, validate)
        self.assertLess(validate, manifest)
        self.assertLess(manifest, attest)

    def test_pull_request_validation_cannot_promote_sign_or_publish(self):
        promotion_validate = PROMOTION.split("  validate:", 1)[1].split(
            "\n  promote:", 1
        )[0]
        trusted_validate = TRUSTED.split("  validate:", 1)[1].split(
            "\n  produce:", 1
        )[0]
        for validate in (promotion_validate, trusted_validate):
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

    def test_external_actions_are_commit_pinned(self):
        for workflow_text in (REFERENCE_SOURCE, PROMOTION, TRUSTED):
            self.assertIn(
                "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
                workflow_text,
            )
            self.assertIn(
                "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
                workflow_text,
            )
        self.assertIn(
            "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
            PROMOTION,
        )
        self.assertIn(
            "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26",
            TRUSTED,
        )


if __name__ == "__main__":
    unittest.main()
