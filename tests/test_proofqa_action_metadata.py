from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACTION = (ROOT / "proofqa/action.yml").read_text(encoding="utf-8")
ROOT_ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/proofqa-action.yml").read_text(
    encoding="utf-8"
)


class ProofQAActionMetadataTests(unittest.TestCase):
    def test_proofqa_is_a_separate_subpath_action(self):
        self.assertIn('name: "ProofQA Release Gate"', ACTION)
        self.assertIn('using: "composite"', ACTION)
        self.assertIn("PythiaLabs Silicon Evidence Gate", ROOT_ACTION)
        self.assertNotIn("ProofQA Release Gate", ROOT_ACTION)

    def test_descriptions_are_quoted_for_github_manifest_parser(self):
        descriptions = [
            line.strip()
            for line in ACTION.splitlines()
            if line.strip().startswith("description:")
        ]
        self.assertGreater(len(descriptions), 5)
        for line in descriptions:
            with self.subTest(line=line):
                self.assertTrue(line.startswith('description: "'))
                self.assertTrue(line.endswith('"'))

    def test_action_exposes_quality_transition_manifest_and_attestation_policy(self):
        for input_name in (
            "summary-path:",
            "transition-report-path:",
            "transition-policy:",
            "transition-manifest-policy:",
            "transition-evidence-dir:",
            "transition-manifest-path:",
            "transition-manifest-receipt-path:",
            "transition-attestation-bundle-path:",
            "transition-attestation-repository:",
            "transition-attestation-signer-workflow:",
            "min-end-to-end:",
            "min-answer-correctness:",
            "min-completion-reliability:",
            "min-provider-reliability:",
            "warn-margin:",
            "max-p95-duration-ms:",
            "time-warn-margin-ms:",
            "unknown-metric-policy:",
            "fail-on:",
            "report-path:",
        ):
            with self.subTest(input_name=input_name):
                self.assertIn(f"  {input_name}", ACTION)

        for output_name in (
            "decision:",
            "should-fail:",
            "report-path:",
            "summary-sha256:",
            "end-to-end-percent:",
            "answer-correctness-percent:",
            "completion-reliability-percent:",
            "provider-reliability-percent:",
            "p95-duration-ms:",
            "transition-status:",
            "transition-phase:",
            "transition-sha256:",
            "transition-manifest-status:",
            "transition-manifest-sha256:",
            "transition-manifest-receipt-sha256:",
            "transition-attestation-status:",
        ):
            with self.subTest(output_name=output_name):
                self.assertIn(f"  {output_name}", ACTION)

    def test_composite_runtime_preflights_binds_and_calls_v5_gate(self):
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            ACTION,
        )
        self.assertNotIn("actions/setup-python@v", ACTION)
        for script in (
            "proofqa_transition_preflight.py",
            "proofqa_transition_manifest.py",
            "proofqa_gate_v5.py",
        ):
            self.assertIn(f'$GITHUB_ACTION_PATH/../scripts/{script}', ACTION)
        self.assertLess(
            ACTION.index("proofqa_transition_preflight.py"),
            ACTION.index("proofqa_transition_manifest.py"),
        )
        self.assertLess(
            ACTION.index("proofqa_transition_manifest.py"),
            ACTION.index("proofqa_gate_v5.py"),
        )
        self.assertIn(
            "PROOFQA_TRANSITION_MANIFEST_POLICY: ${{ inputs.transition-manifest-policy }}",
            ACTION,
        )
        self.assertIn(
            "PROOFQA_TRANSITION_MANIFEST_RECEIPT_PATH: ${{ inputs.transition-manifest-receipt-path }}",
            ACTION,
        )

    def test_attestation_verification_is_exact_and_fail_closed(self):
        self.assertEqual(ACTION.count("gh attestation verify"), 2)
        self.assertIn('--signer-workflow "$EXPECTED_SIGNER_WORKFLOW"', ACTION)
        self.assertEqual(ACTION.count("--deny-self-hosted-runners"), 2)
        self.assertIn('--bundle "$ATTESTATION_BUNDLE"', ACTION)
        self.assertIn("GH_TOKEN: ${{ github.token }}", ACTION)
        self.assertNotIn("id-token: write", ACTION)
        self.assertNotIn("attestations: write", ACTION)
        self.assertNotIn("actions/attest", ACTION)

    def test_smoke_workflow_remains_read_only(self):
        permissions = WORKFLOW.split("\njobs:", 1)[0]
        self.assertIn("  contents: read", permissions)
        self.assertNotIn("contents: write", permissions)
        self.assertNotIn("id-token: write", permissions)
        self.assertNotIn("attestations: write", permissions)
        self.assertIn("uses: ./proofqa", WORKFLOW)

    def test_smoke_workflow_uses_pinned_external_actions(self):
        self.assertIn(
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
            WORKFLOW,
        )
        self.assertIn(
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            WORKFLOW,
        )
        self.assertNotIn("actions/checkout@v", WORKFLOW)
        self.assertNotIn("actions/upload-artifact@v", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
