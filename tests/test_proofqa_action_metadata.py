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

    def test_action_exposes_quality_time_and_transition_policy(self):
        for input_name in (
            "summary-path:",
            "transition-report-path:",
            "transition-policy:",
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
        ):
            with self.subTest(output_name=output_name):
                self.assertIn(f"  {output_name}", ACTION)

    def test_composite_runtime_is_pinned_and_preflights_transition(self):
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            ACTION,
        )
        self.assertNotIn("actions/setup-python@v", ACTION)
        self.assertIn(
            'python "$GITHUB_ACTION_PATH/../scripts/proofqa_transition_preflight.py"',
            ACTION,
        )
        self.assertIn(
            'python "$GITHUB_ACTION_PATH/../scripts/proofqa_gate_v4.py"',
            ACTION,
        )
        self.assertLess(
            ACTION.index("proofqa_transition_preflight.py"),
            ACTION.index("proofqa_gate_v4.py"),
        )
        self.assertIn("PROOFQA_SUMMARY_PATH: ${{ inputs.summary-path }}", ACTION)
        self.assertIn(
            "PROOFQA_TRANSITION_REPORT_PATH: ${{ inputs.transition-report-path }}",
            ACTION,
        )
        self.assertIn(
            "PROOFQA_TRANSITION_POLICY: ${{ inputs.transition-policy }}",
            ACTION,
        )
        self.assertIn(
            "PROOFQA_MAX_P95_DURATION_MS: ${{ inputs.max-p95-duration-ms }}",
            ACTION,
        )
        self.assertIn("PROOFQA_FAIL_ON: ${{ inputs.fail-on }}", ACTION)

    def test_smoke_workflow_is_read_only_and_exercises_transition_decisions(self):
        permissions = WORKFLOW.split("\njobs:", 1)[0]
        self.assertIn("  contents: read", permissions)
        self.assertNotIn("contents: write", permissions)
        self.assertNotIn("id-token: write", permissions)
        self.assertEqual(WORKFLOW.count("uses: ./proofqa"), 7)
        self.assertIn("- name: PASS time decision", WORKFLOW)
        self.assertIn("- name: WARN time decision", WORKFLOW)
        self.assertIn("- name: BLOCK time decision fails the action", WORKFLOW)
        self.assertIn(
            "Preserve v2 compatibility with transition and time gates disabled",
            WORKFLOW,
        )
        self.assertIn("- name: Require VERIFIED transition", WORKFLOW)
        self.assertIn("Warn on unfinished transition during adoption", WORKFLOW)
        self.assertIn("Block recalibration under strict transition policy", WORKFLOW)
        self.assertIn("continue-on-error: true", WORKFLOW)
        self.assertIn('[[ "$TRANSITION_STATUS" == "VERIFIED" ]]', WORKFLOW)
        self.assertIn('[[ "$TRANSITION_PHASE" == "EXPAND" ]]', WORKFLOW)
        self.assertIn('[[ "$STEP_OUTCOME" == "failure" ]]', WORKFLOW)

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
