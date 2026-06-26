from pathlib import Path
import unittest


WORKFLOW_PATH = Path(".github/workflows/release.yml")
ATTEST_ACTION_SHA = "59d89421af93a897026c735860bf21b6eb4f7b26"


class ReleaseAttestationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.publish = cls.workflow.split("\n  publish:\n", 1)[1]

    def test_publish_job_has_keyless_signing_permissions(self):
        permissions = self.publish.split("\n    steps:\n", 1)[0]
        self.assertIn("      contents: write", permissions)
        self.assertIn("      id-token: write", permissions)
        self.assertIn("      attestations: write", permissions)
        self.assertIn("      artifact-metadata: write", permissions)

    def test_attestation_action_is_pinned_and_runs_only_for_new_release(self):
        expected = f"uses: actions/attest@{ATTEST_ACTION_SHA}"
        self.assertEqual(self.publish.count(expected), 1)
        self.assertNotIn("uses: actions/attest@v", self.publish)

        inspect_index = self.publish.index("- name: Inspect existing release tag")
        attest_index = self.publish.index("- name: Generate keyless build provenance")
        publish_index = self.publish.index("- name: Publish GitHub Release")
        self.assertLess(inspect_index, attest_index)
        self.assertLess(attest_index, publish_index)

        attestation_step = self.publish[attest_index:publish_index]
        self.assertIn(
            "if: steps.existing.outputs.exists == 'false' && steps.release.outputs.asset != ''",
            attestation_step,
        )

    def test_all_release_metadata_files_are_attested(self):
        attestation_step = self.publish.split(
            "- name: Generate keyless build provenance", 1
        )[1].split("- name: Preserve Sigstore attestation bundle", 1)[0]
        self.assertIn("${{ steps.release.outputs.asset }}", attestation_step)
        self.assertIn("${{ steps.release.outputs.checksum }}", attestation_step)
        self.assertIn("${{ steps.release.outputs.provenance }}", attestation_step)

    def test_sigstore_bundle_is_published_and_downloaded(self):
        self.assertIn("#Keyless Sigstore attestation bundle", self.publish)
        self.assertIn('attestation_name="$(basename "$ATTESTATION")"', self.publish)
        self.assertIn(
            'gh release download "$TAG" --repo "$GITHUB_REPOSITORY" --pattern "$attestation_name"',
            self.publish,
        )
        self.assertIn(
            '--expected "$ATTESTATION" \\\n              --actual "$downloaded_attestation"',
            self.publish,
        )

    def test_online_and_offline_verification_enforce_signer_identity(self):
        self.assertGreaterEqual(self.publish.count("gh attestation verify"), 2)
        self.assertIn('--repo "$GITHUB_REPOSITORY"', self.publish)
        self.assertIn('--signer-workflow "$signer_workflow"', self.publish)
        self.assertIn("--deny-self-hosted-runners", self.publish)
        self.assertIn('--bundle "$downloaded_attestation"', self.publish)
        self.assertIn("--format json", self.publish)

    def test_legacy_immutable_release_noop_is_preserved(self):
        self.assertIn("Verify existing older release is readable", self.publish)
        self.assertIn(
            "steps.existing.outputs.same_commit == 'false'", self.publish
        )


if __name__ == "__main__":
    unittest.main()
