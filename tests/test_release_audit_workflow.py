from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/release-audit.yml").read_text(encoding="utf-8")


class IndependentReleaseAuditWorkflowTests(unittest.TestCase):
    def test_workflow_is_read_only_and_has_no_oidc_signing_permission(self):
        permissions = WORKFLOW.split("\nconcurrency:", 1)[0]
        self.assertIn("  contents: read", permissions)
        self.assertIn("  attestations: read", permissions)
        self.assertNotIn("contents: write", permissions)
        self.assertNotIn("attestations: write", permissions)
        self.assertNotIn("id-token: write", permissions)
        self.assertNotIn("artifact-metadata: write", permissions)

    def test_actions_are_pinned_to_commit_shas(self):
        self.assertIn(
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
            WORKFLOW,
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            WORKFLOW,
        )
        self.assertNotIn("actions/checkout@v", WORKFLOW)
        self.assertNotIn("actions/setup-python@v", WORKFLOW)

    def test_audit_downloads_exact_release_files(self):
        self.assertIn("Require exact public Release asset set", WORKFLOW)
        self.assertIn("gh release download", WORKFLOW)
        self.assertIn("scripts/audit_published_release.py", WORKFLOW)
        self.assertIn("release-attestation.sigstore.json", WORKFLOW)

    def test_online_and_bundle_attestation_verification_are_required(self):
        self.assertGreaterEqual(WORKFLOW.count("gh attestation verify"), 2)
        self.assertIn('--signer-workflow "$signer_workflow"', WORKFLOW)
        self.assertIn("--deny-self-hosted-runners", WORKFLOW)
        self.assertIn('--bundle "$bundle"', WORKFLOW)
        self.assertIn("--format json", WORKFLOW)

    def test_auditor_does_not_publish_or_modify_release(self):
        forbidden = (
            "gh release create",
            "gh release upload",
            "gh release edit",
            "gh release delete",
            "git push",
            "actions/attest@",
        )
        for command in forbidden:
            with self.subTest(command=command):
                self.assertNotIn(command, WORKFLOW)


if __name__ == "__main__":
    unittest.main()
