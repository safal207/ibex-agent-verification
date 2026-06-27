from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_WORKFLOW = (
    ROOT / ".github/workflows/proofqa-transition-source.yml"
).read_text(encoding="utf-8")
TRUSTED_WORKFLOW = (
    ROOT / ".github/workflows/trusted-transition-artifact.yml"
).read_text(encoding="utf-8")


class TrustedTransitionArtifactWorkflowTests(unittest.TestCase):
    def test_source_workflow_is_read_only_and_unsigned(self):
        self.assertIn('workflows: ["ProofQA Release Gate Action"]', SOURCE_WORKFLOW)
        self.assertIn("workflow_run.conclusion == 'success'", SOURCE_WORKFLOW)
        self.assertIn("workflow_run.event == 'push'", SOURCE_WORKFLOW)
        self.assertIn("workflow_run.head_branch == 'main'", SOURCE_WORKFLOW)
        self.assertIn(
            "workflow_run.head_repository.full_name == github.repository",
            SOURCE_WORKFLOW,
        )
        self.assertIn("contents: read", SOURCE_WORKFLOW)
        self.assertNotIn("id-token", SOURCE_WORKFLOW)
        self.assertNotIn("actions/attest", SOURCE_WORKFLOW)
        self.assertNotIn("issues: write", SOURCE_WORKFLOW)

    def test_source_artifact_is_exact_and_validated_before_upload(self):
        build_position = SOURCE_WORKFLOW.index(
            "scripts/trusted_transition_reference_source.py"
        )
        validate_position = SOURCE_WORKFLOW.index(
            "scripts/production_transition_source.py"
        )
        upload_position = SOURCE_WORKFLOW.index(
            "name: Upload exact reference source"
        )
        self.assertLess(build_position, validate_position)
        self.assertLess(validate_position, upload_position)
        self.assertIn(
            "name: proofqa-transition-source-${{ github.event.workflow_run.head_sha }}",
            SOURCE_WORKFLOW,
        )
        self.assertIn("path: artifacts/proofqa-transition-source", SOURCE_WORKFLOW)
        self.assertIn("persist-credentials: false", SOURCE_WORKFLOW)

    def test_trusted_validation_job_has_no_privileged_permissions(self):
        validate = TRUSTED_WORKFLOW.split("  validate:", 1)[1].split(
            "\n  produce:", 1
        )[0]
        self.assertIn("contents: read", validate)
        self.assertNotIn("actions: read", validate)
        self.assertNotIn("id-token", validate)
        self.assertNotIn("attestations", validate)
        self.assertNotIn("artifact-metadata", validate)

    def test_privileged_job_requires_exact_successful_source_workflow(self):
        self.assertIn(
            'workflows: ["ProofQA Transition Source Artifact"]',
            TRUSTED_WORKFLOW,
        )
        for text in (
            "workflow_run.conclusion == 'success'",
            "workflow_run.event == 'workflow_run'",
            "workflow_run.head_branch == 'main'",
            "workflow_run.head_repository.full_name == github.repository",
        ):
            self.assertIn(text, TRUSTED_WORKFLOW)
        self.assertNotIn("pull_request_target", TRUSTED_WORKFLOW)
        self.assertNotIn("workflow_dispatch", TRUSTED_WORKFLOW)

    def test_raw_download_is_bound_and_fail_closed(self):
        self.assertIn("actions: read", TRUSTED_WORKFLOW)
        self.assertIn("Select exact source artifact", TRUSTED_WORKFLOW)
        self.assertIn("--expected-run-id", TRUSTED_WORKFLOW)
        self.assertIn("--expected-run-attempt", TRUSTED_WORKFLOW)
        self.assertIn("--expected-head-repository-id", TRUSTED_WORKFLOW)
        self.assertIn("artifact-ids:", TRUSTED_WORKFLOW)
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", TRUSTED_WORKFLOW)
        self.assertIn("skip-decompress: true", TRUSTED_WORKFLOW)
        self.assertIn("digest-mismatch: error", TRUSTED_WORKFLOW)

    def test_source_is_extracted_and_validated_before_manifest(self):
        extract_position = TRUSTED_WORKFLOW.index(
            "scripts/trusted_transition_artifact.py extract"
        )
        validate_position = TRUSTED_WORKFLOW.index(
            "scripts/production_transition_source.py"
        )
        manifest_position = TRUSTED_WORKFLOW.index(
            "scripts/proofqa_transition_manifest_builder.py"
        )
        attest_position = TRUSTED_WORKFLOW.index("actions/attest@")
        self.assertLess(extract_position, validate_position)
        self.assertLess(validate_position, manifest_position)
        self.assertLess(manifest_position, attest_position)
        self.assertIn(
            "--report artifacts/trusted-transition-ingested/source-artifact-extraction.json",
            TRUSTED_WORKFLOW,
        )
        self.assertIn(
            "--report artifacts/trusted-transition-ingested/source-validation.json",
            TRUSTED_WORKFLOW,
        )

    def test_signer_and_attestation_policy_are_explicit(self):
        self.assertEqual(TRUSTED_WORKFLOW.count("actions/attest@"), 1)
        self.assertIn(
            "subject-path: artifacts/trusted-transition-ingested/bundle/manifest.json",
            TRUSTED_WORKFLOW,
        )
        self.assertIn("transition-manifest-policy: require-attested", TRUSTED_WORKFLOW)
        self.assertIn(
            "/.github/workflows/trusted-transition-artifact.yml",
            TRUSTED_WORKFLOW,
        )
        self.assertIn("trusted_transition_artifact_audit.py", TRUSTED_WORKFLOW)

    def test_all_external_actions_are_commit_pinned(self):
        for workflow in (SOURCE_WORKFLOW, TRUSTED_WORKFLOW):
            self.assertIn(
                "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
                workflow,
            )
            self.assertIn(
                "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
                workflow,
            )
        self.assertIn(
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            SOURCE_WORKFLOW,
        )
        self.assertIn(
            "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
            TRUSTED_WORKFLOW,
        )
        self.assertIn(
            "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26",
            TRUSTED_WORKFLOW,
        )
        self.assertIn(
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            TRUSTED_WORKFLOW,
        )


if __name__ == "__main__":
    unittest.main()
