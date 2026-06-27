import json
import tempfile
import unittest
from pathlib import Path

from scripts import proofqa_gate_v3 as base
from scripts.proofqa_gate_v4 import (
    GatePolicyV4,
    ProofQAGateV4Error,
    build_report,
    evaluate_gate,
    policy_from_environment,
    run,
    validate_transition_report,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/proofqa"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def policy(transition_policy: str) -> GatePolicyV4:
    return GatePolicyV4(
        scorecard=base.GatePolicyV3(
            min_end_to_end=90.0,
            min_answer_correctness=90.0,
            min_completion_reliability=95.0,
            min_provider_reliability=95.0,
            warn_margin=3.0,
            max_p95_duration_ms=1000.0,
            time_warn_margin_ms=250.0,
            unknown_metric_policy="block",
            fail_on="block",
            policy_name="transition-test",
        ),
        transition_policy=transition_policy,
    )


class ProofQATransitionGateTests(unittest.TestCase):
    def test_default_policy_preserves_existing_scorecard_behavior(self):
        parsed = policy_from_environment({})
        self.assertEqual(parsed.transition_policy, "ignore")

        result = evaluate_gate(
            summary=load_fixture("summary-time-pass.json"),
            policy=parsed,
            transition=None,
        )
        self.assertEqual(result["decision"], "PASS")
        finding = result["findings"][-1]
        self.assertEqual(finding["axis"], "transition_phase")
        self.assertFalse(finding["enabled"])
        self.assertIsNone(result["transition"])

    def test_warn_policy_surfaces_unfinished_transition_without_blocking(self):
        transition = validate_transition_report(
            load_fixture("transition-in-progress.json")
        )
        result = evaluate_gate(
            summary=load_fixture("summary-time-pass.json"),
            policy=policy("warn"),
            transition=transition,
        )
        self.assertEqual(result["decision"], "WARN")
        self.assertFalse(result["should_fail"])
        self.assertEqual(result["findings"][-1]["status"], "WARN")
        self.assertEqual(result["transition"]["phase"], "EXPAND")

    def test_require_verified_accepts_only_converged_transition(self):
        verified = validate_transition_report(load_fixture("transition-verified.json"))
        recalibrate = validate_transition_report(
            load_fixture("transition-recalibrate.json")
        )

        passed = evaluate_gate(
            summary=load_fixture("summary-time-pass.json"),
            policy=policy("require-verified"),
            transition=verified,
        )
        blocked = evaluate_gate(
            summary=load_fixture("summary-time-pass.json"),
            policy=policy("require-verified"),
            transition=recalibrate,
        )

        self.assertEqual(passed["decision"], "PASS")
        self.assertEqual(passed["findings"][-1]["status"], "PASS")
        self.assertEqual(blocked["decision"], "BLOCK")
        self.assertTrue(blocked["should_fail"])
        self.assertEqual(blocked["findings"][-1]["status"], "BLOCK")
        self.assertIn("require-verified", blocked["findings"][-1]["message"])

    def test_verified_label_cannot_hide_inconsistent_axes(self):
        forged = load_fixture("transition-verified.json")
        forged["axes"]["space"]["status"] = "WAIT"
        with self.assertRaisesRegex(
            ProofQAGateV4Error,
            "requires PASS on time, intention, and space",
        ):
            validate_transition_report(forged)

    def test_in_progress_cannot_contain_block_axis(self):
        malformed = load_fixture("transition-in-progress.json")
        malformed["axes"]["intention"]["status"] = "BLOCK"
        with self.assertRaisesRegex(
            ProofQAGateV4Error,
            "cannot contain a BLOCK axis",
        ):
            validate_transition_report(malformed)

    def test_recalibrate_requires_reason(self):
        malformed = load_fixture("transition-recalibrate.json")
        malformed["issues"] = []
        malformed["axes"]["intention"]["status"] = "WAIT"
        with self.assertRaisesRegex(
            ProofQAGateV4Error,
            "requires an issue or a BLOCK axis",
        ):
            validate_transition_report(malformed)

    def test_non_ignored_policy_requires_transition_path(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "gate.json"
            environment = {
                "PROOFQA_SUMMARY_PATH": str(FIXTURES / "summary-time-pass.json"),
                "PROOFQA_TRANSITION_POLICY": "require-verified",
                "PROOFQA_REPORT_PATH": str(report),
            }
            with self.assertRaisesRegex(
                ProofQAGateV4Error,
                "transition-report-path is required",
            ):
                run(environment)
            self.assertFalse(report.exists())

    def test_report_binds_transition_path_and_digest(self):
        transition_path = FIXTURES / "transition-verified.json"
        transition = validate_transition_report(load_fixture("transition-verified.json"))
        selected_policy = policy("require-verified")
        summary = load_fixture("summary-time-pass.json")
        evaluation = evaluate_gate(
            summary=summary,
            policy=selected_policy,
            transition=transition,
        )
        report = build_report(
            summary_path=FIXTURES / "summary-time-pass.json",
            summary=summary,
            transition_path=transition_path,
            policy=selected_policy,
            evaluation=evaluation,
        )
        self.assertEqual(report["schema_version"], 3)
        self.assertEqual(report["transition"]["status"], "VERIFIED")
        self.assertEqual(
            report["source"]["transition_report_sha256"],
            base._sha256(transition_path),
        )
        self.assertEqual(report["policy"]["transition_policy"], "require-verified")


if __name__ == "__main__":
    unittest.main()
