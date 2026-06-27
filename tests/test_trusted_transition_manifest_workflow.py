from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/trusted-transition-manifest.yml").read_text(
    encoding="utf-8"
)


class TrustedTransitionManifestWorkflowTests(unittest.TestCase):
    def test_validation_job_is_read_only(self):
        validate = WORKFLOW.split("  validate:", 1)[1].split("\n  produce:", 1)[0]
        self.assertIn("if: github.event_name == 'pull_request'", validate)
        self.assertIn("contents: read", validate)
        self.assertNotIn("actions/attest", validate)
        self.assertNotIn("id-token", validate)

    def test_producer_requires_green_same_repo_main_push(self):
        for text in (
            "workflow_run.conclusion == 'success'",
            "workflow_run.event == 'push'",
            "workflow_run.head_branch == 'main'",
            "workflow_run.head_repository.full_name == github.repository",
        ):
            self.assertIn(text, WORKFLOW)
        self.assertNotIn("pull_request_target", WORKFLOW)
        self.assertNotIn("workflow_dispatch", WORKFLOW)

    def test_exact_green_commit_is_checked_out_without_credentials(self):
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", WORKFLOW)
        self.assertIn("persist-credentials: false", WORKFLOW)
        self.assertIn('git rev-parse HEAD', WORKFLOW)
        self.assertIn("git diff --exit-code", WORKFLOW)

    def test_signing_subject_and_verifier_identity_are_explicit(self):
        self.assertEqual(WORKFLOW.count("actions/attest@"), 1)
        self.assertIn(
            "subject-path: artifacts/trusted-transition-reference/bundle/manifest.json",
            WORKFLOW,
        )
        self.assertIn("transition-manifest-policy: require-attested", WORKFLOW)
        self.assertIn("/.github/workflows/trusted-transition-manifest.yml", WORKFLOW)

    def test_external_actions_are_commit_pinned(self):
        for pin in (
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        ):
            self.assertIn(pin, WORKFLOW)


if __name__ == "__main__":
    unittest.main()
