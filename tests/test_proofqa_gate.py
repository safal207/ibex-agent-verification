import json
import tempfile
import unittest
from pathlib import Path

from scripts.proofqa_gate import (
    GatePolicy,
    ProofQAGateError,
    evaluate_gate,
    policy_from_environment,
    run,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/proofqa"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def policy(**overrides) -> GatePolicy:
    values = {
        "min_end_to_end": 90.0,
        "min_answer_correctness": 90.0,
        "min_completion_reliability": 95.0,
        "min_provider_reliability": 95.0,
        "warn_margin": 3.0,
        "unknown_metric_policy": "block",
        "fail_on": "block",
        "policy_name": "test-policy",
    }
    values.update(overrides)
    return GatePolicy(**values)


class ProofQAGateTests(unittest.TestCase):
    def test_perfect_scorecard_passes(self):
        result = evaluate_gate(
            summary=load_fixture("summary-pass.json"),
            policy=policy(),
        )
        self.assertEqual(result["decision"], "PASS")
        self.assertFalse(result["should_fail"])
        self.assertEqual(
            {finding["status"] for finding in result["findings"]},
            {"PASS"},
        )

    def test_warning_margin_does_not_hide_threshold_pass(self):
        result = evaluate_gate(
            summary=load_fixture("summary-warn.json"),
            policy=policy(min_end_to_end=95.0),
        )
        self.assertEqual(result["decision"], "WARN")
        self.assertFalse(result["should_fail"])
        warning = next(
            finding for finding in result["findings"] if finding["status"] == "WARN"
        )
        self.assertEqual(warning["axis"], "end_to_end")
        self.assertEqual(warning["actual_percent"], 96.551724)

    def test_blocking_scorecard_fails_default_enforcement(self):
        result = evaluate_gate(
            summary=load_fixture("summary-block.json"),
            policy=policy(),
        )
        self.assertEqual(result["decision"], "BLOCK")
        self.assertTrue(result["should_fail"])
        blocked_axes = {
            finding["axis"]
            for finding in result["findings"]
            if finding["status"] == "BLOCK"
        }
        self.assertEqual(
            blocked_axes,
            {"end_to_end", "completion_reliability", "provider_reliability"},
        )

    def test_fail_on_modes_change_enforcement_not_decision(self):
        summary = load_fixture("summary-warn.json")
        warn_result = evaluate_gate(
            summary=summary,
            policy=policy(min_end_to_end=95.0, fail_on="warn"),
        )
        never_result = evaluate_gate(
            summary=summary,
            policy=policy(min_end_to_end=95.0, fail_on="never"),
        )
        self.assertEqual(warn_result["decision"], "WARN")
        self.assertTrue(warn_result["should_fail"])
        self.assertEqual(never_result["decision"], "WARN")
        self.assertFalse(never_result["should_fail"])

    def test_unknown_metric_policy_is_explicit(self):
        summary = load_fixture("summary-pass.json")
        summary["scorecard"]["answer_correctness"]["percent"] = None

        blocked = evaluate_gate(summary=summary, policy=policy())
        warned = evaluate_gate(
            summary=summary,
            policy=policy(unknown_metric_policy="warn"),
        )
        ignored = evaluate_gate(
            summary=summary,
            policy=policy(unknown_metric_policy="ignore"),
        )
        self.assertEqual(blocked["decision"], "BLOCK")
        self.assertEqual(warned["decision"], "WARN")
        self.assertEqual(ignored["decision"], "PASS")

    def test_legacy_and_malformed_scorecards_fail_closed(self):
        legacy = load_fixture("summary-pass.json")
        legacy["scorecard_version"] = 1
        with self.assertRaisesRegex(ProofQAGateError, "scorecard_version must equal 2"):
            evaluate_gate(summary=legacy, policy=policy())

        malformed = load_fixture("summary-pass.json")
        malformed["scorecard"]["provider_reliability"]["percent"] = "100"
        with self.assertRaisesRegex(ProofQAGateError, "must be a number or null"):
            evaluate_gate(summary=malformed, policy=policy())

    def test_policy_environment_rejects_invalid_values(self):
        with self.assertRaisesRegex(ProofQAGateError, "min-end-to-end"):
            policy_from_environment({"PROOFQA_MIN_END_TO_END": "101"})
        with self.assertRaisesRegex(ProofQAGateError, "fail-on"):
            policy_from_environment({"PROOFQA_FAIL_ON": "sometimes"})
        with self.assertRaisesRegex(ProofQAGateError, "unknown-metric-policy"):
            policy_from_environment({"PROOFQA_UNKNOWN_METRIC_POLICY": "guess"})

    def test_cli_run_writes_report_summary_and_machine_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "gate-report.json"
            outputs = root / "github-output.txt"
            step_summary = root / "step-summary.md"
            exit_code = run(
                {
                    "PROOFQA_SUMMARY_PATH": str(FIXTURES / "summary-pass.json"),
                    "PROOFQA_REPORT_PATH": str(report),
                    "PROOFQA_POLICY_NAME": "mobile-release",
                    "GITHUB_OUTPUT": str(outputs),
                    "GITHUB_STEP_SUMMARY": str(step_summary),
                }
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            output_text = outputs.read_text(encoding="utf-8")
            markdown = step_summary.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["decision"], "PASS")
        self.assertEqual(payload["policy"]["name"], "mobile-release")
        self.assertRegex(payload["source"]["summary_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("decision=PASS\n", output_text)
        self.assertIn("end-to-end-percent=100.000000\n", output_text)
        self.assertIn("## ✅ ProofQA Release Gate — PASS", markdown)

    def test_report_path_cannot_overwrite_source_summary(self):
        summary = FIXTURES / "summary-pass.json"
        with self.assertRaisesRegex(ProofQAGateError, "must differ from summary-path"):
            run(
                {
                    "PROOFQA_SUMMARY_PATH": str(summary),
                    "PROOFQA_REPORT_PATH": str(summary),
                }
            )


if __name__ == "__main__":
    unittest.main()
