from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / ".github/workflows/github-release-runtime-verification.yml").read_text(encoding="utf-8")
TRUSTED = (ROOT / ".github/workflows/trusted-transition-artifact.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github/workflows/github-release-production-deployment.yml").read_text(encoding="utf-8")


class TrustedTransitionArtifactWorkflowTests(unittest.TestCase):
    def test_runtime_requires_successful_release_deployment(self):
        self.assertIn('workflows: ["GitHub Release Production Deployment"]', RUNTIME)
        self.assertIn("workflow_run.conclusion == 'success'", RUNTIME)
        self.assertIn("workflow_run.event == 'workflow_run'", RUNTIME)
        self.assertIn("workflow_run.head_branch == 'main'", RUNTIME)
        self.assertIn("environment: ibex-runtime-verification", RUNTIME)
        self.assertIn("actions: read", RUNTIME)
        self.assertNotIn("contents: write", RUNTIME)
        self.assertNotIn("id-token", RUNTIME)

    def test_runtime_executes_only_live_release_bytes(self):
        download = RUNTIME.index("name: Download public release asset")
        extract = RUNTIME.index("name: Extract live release bytes")
        manifest = RUNTIME.index("name: Build runtime manifest")
        install = RUNTIME.index("name: Build and install exact wheel")
        execute = RUNTIME.index("name: Capture install and execute installed CLI")
        source = RUNTIME.index("name: Build and validate runtime source")
        self.assertLess(download, extract)
        self.assertLess(extract, manifest)
        self.assertLess(manifest, install)
        self.assertLess(install, execute)
        self.assertLess(execute, source)
        self.assertIn("gh release download", RUNTIME)
        self.assertIn("--no-index --no-deps", RUNTIME)
        self.assertIn("runtime-venv/bin/ibex-av", RUNTIME)
        self.assertIn("github_release_runtime_source.py build", RUNTIME)

    def test_runtime_pr_validation_is_read_only(self):
        validate = RUNTIME.split("  validate:", 1)[1].split("\n  execute:", 1)[0]
        self.assertIn("contents: read", validate)
        self.assertIn("python -m pip wheel", validate)
        self.assertNotIn("actions: read", validate)
        self.assertNotIn("contents: write", validate)
        self.assertNotIn("id-token", validate)

    def test_signer_accepts_only_runtime_workflow(self):
        self.assertIn('workflows: ["GitHub Release Runtime Verification"]', TRUSTED)
        self.assertIn("SOURCE_WORKFLOW: .github/workflows/github-release-runtime-verification.yml", TRUSTED)
        self.assertIn("DESTINATION_ENVIRONMENT: ibex-runtime-verification", TRUSTED)
        self.assertIn("github_release_runtime_source.py observe", TRUSTED)
        self.assertNotIn('workflows: ["GitHub Release Production Deployment"]', TRUSTED)

    def test_runtime_observation_precedes_attestation(self):
        extract = TRUSTED.index("name: Extract exact runtime source bytes")
        observe = TRUSTED.index("name: Independently observe runtime and live release")
        validate = TRUSTED.index("name: Validate exact runtime source")
        manifest = TRUSTED.index("proofqa_transition_manifest_builder.py")
        attest = TRUSTED.index("uses: actions/attest@")
        self.assertLess(extract, observe)
        self.assertLess(observe, validate)
        self.assertLess(validate, manifest)
        self.assertLess(manifest, attest)

    def test_release_and_runtime_cannot_sign(self):
        self.assertNotIn("actions/attest@", RELEASE)
        self.assertNotIn("actions/attest@", RUNTIME)
        self.assertIn("actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26", TRUSTED)

    def test_external_actions_are_commit_pinned(self):
        for workflow in (RELEASE, RUNTIME, TRUSTED):
            self.assertIn("actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5", workflow)
            self.assertIn("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", workflow)


if __name__ == "__main__":
    unittest.main()
