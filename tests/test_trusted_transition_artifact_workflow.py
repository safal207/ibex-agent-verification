from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (
    ROOT / ".github/workflows/github-release-runtime-verification.yml"
).read_text(encoding="utf-8")
TRUSTED = (
    ROOT / ".github/workflows/trusted-transition-artifact.yml"
).read_text(encoding="utf-8")
RELEASE = (
    ROOT / ".github/workflows/github-release-production-deployment.yml"
).read_text(encoding="utf-8")


def job_block(workflow: str, name: str, next_name: str | None = None) -> str:
    start = workflow.index(f"  {name}:")
    if next_name is None:
        return workflow[start:]
    end = workflow.index(f"\n  {next_name}:", start)
    return workflow[start:end]


class TrustedTransitionArtifactWorkflowTests(unittest.TestCase):
    def test_runtime_requires_successful_release_deployment(self):
        self.assertIn(
            'workflows: ["GitHub Release Production Deployment"]', RUNTIME
        )
        execute = job_block(RUNTIME, "execute", "sign")
        self.assertIn("workflow_run.conclusion == 'success'", execute)
        self.assertIn("workflow_run.event == 'workflow_run'", execute)
        self.assertIn("workflow_run.head_branch == 'main'", execute)
        self.assertIn("environment: ibex-runtime-verification", execute)
        self.assertIn("actions: read", execute)
        self.assertNotIn("contents: write", execute)
        self.assertNotIn("id-token", execute)

    def test_runtime_executes_only_live_release_bytes(self):
        execute = job_block(RUNTIME, "execute", "sign")
        download = execute.index("name: Download public release asset")
        extract = execute.index("name: Extract live release bytes")
        manifest = execute.index("name: Build runtime manifest")
        install = execute.index("name: Build and install exact wheel")
        run_cli = execute.index(
            "name: Capture measured install and execute installed CLI"
        )
        source = execute.index("name: Build and validate runtime source")
        self.assertLess(download, extract)
        self.assertLess(extract, manifest)
        self.assertLess(manifest, install)
        self.assertLess(install, run_cli)
        self.assertLess(run_cli, source)
        self.assertIn("gh release download", execute)
        self.assertIn("--no-index --no-deps", execute)
        self.assertIn("runtime-venv/bin/ibex-av", execute)
        self.assertIn("github_release_runtime_source.py build", execute)
        self.assertIn('--isolated "$ISOLATED"', execute)

    def test_runtime_pr_paths_include_contract_dependencies(self):
        pull_request = RUNTIME.split("  workflow_run:", 1)[0]
        for path in (
            "scripts/proofqa_transition_manifest_builder.py",
            "scripts/production_transition_source.py",
            "tests/test_github_release_production_source.py",
            "tests/test_production_transition_source.py",
            "tests/test_trusted_transition_artifact_workflow.py",
        ):
            self.assertIn(path, pull_request)

    def test_runtime_pr_validation_is_read_only(self):
        validate = job_block(RUNTIME, "validate", "execute")
        self.assertIn("contents: read", validate)
        self.assertIn("python -m pip wheel", validate)
        self.assertNotIn("actions: read", validate)
        self.assertNotIn("contents: write", validate)
        self.assertNotIn("id-token", validate)

    def test_signer_is_reusable_and_removes_fourth_workflow_run_hop(self):
        self.assertIn("workflow_call:", TRUSTED)
        self.assertNotIn(
            'workflows: ["GitHub Release Runtime Verification"]', TRUSTED
        )
        sign = job_block(RUNTIME, "sign")
        self.assertIn("needs: execute", sign)
        self.assertIn(
            "uses: ./.github/workflows/trusted-transition-artifact.yml", sign
        )
        self.assertIn("source_run_id: ${{ github.run_id }}", sign)
        self.assertIn("id-token: write", sign)
        self.assertIn("attestations: write", sign)

    def test_signer_privileges_are_not_granted_to_runtime_execute(self):
        execute = job_block(RUNTIME, "execute", "sign")
        sign = job_block(RUNTIME, "sign")
        for privilege in (
            "issues: write",
            "id-token: write",
            "attestations: write",
            "artifact-metadata: write",
        ):
            self.assertNotIn(privilege, execute)
            self.assertIn(privilege, sign)

    def test_signer_observations_are_moved_into_attested_bundle(self):
        produce = job_block(TRUSTED, "produce")
        bind = produce.index(
            "name: Bind signer observations into attested bundle"
        )
        manifest = produce.index("name: Build exact final manifest")
        attest = produce.index("uses: actions/attest@")
        self.assertLess(bind, manifest)
        self.assertLess(manifest, attest)
        for name in (
            "source-artifacts-api.json",
            "source-artifact-selection.json",
            "source-artifact-extraction.json",
            "live-release.json",
            "runtime-observation.json",
            "source-validation.json",
        ):
            self.assertIn(name, produce)
        self.assertIn("bundle/signer", produce)

    def test_runtime_observation_precedes_attestation(self):
        produce = job_block(TRUSTED, "produce")
        extract = produce.index("name: Extract exact runtime source bytes")
        observe = produce.index(
            "name: Independently observe runtime and live release"
        )
        validate = produce.index("name: Validate exact runtime source")
        bind = produce.index(
            "name: Bind signer observations into attested bundle"
        )
        manifest = produce.index("proofqa_transition_manifest_builder.py")
        attest = produce.index("uses: actions/attest@")
        self.assertLess(extract, observe)
        self.assertLess(observe, validate)
        self.assertLess(validate, bind)
        self.assertLess(bind, manifest)
        self.assertLess(manifest, attest)

    def test_release_and_runtime_execute_cannot_sign(self):
        self.assertNotIn("actions/attest@", RELEASE)
        execute = job_block(RUNTIME, "execute", "sign")
        self.assertNotIn("actions/attest@", execute)
        self.assertIn(
            "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26",
            TRUSTED,
        )

    def test_external_actions_are_commit_pinned(self):
        for workflow in (RELEASE, RUNTIME, TRUSTED):
            self.assertIn(
                "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
                workflow,
            )
            self.assertIn(
                "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
                workflow,
            )
        self.assertIn(
            "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
            TRUSTED,
        )
        for workflow in (RUNTIME, TRUSTED):
            self.assertIn(
                "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
                workflow,
            )


if __name__ == "__main__":
    unittest.main()
