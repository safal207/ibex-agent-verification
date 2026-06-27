import json
import tempfile
import unittest
from pathlib import Path

from scripts.proofqa_transition_preflight import (
    ProofQATransitionPreflightError,
    run,
    validate_transition_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/proofqa"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ProofQATransitionPreflightTests(unittest.TestCase):
    def test_verified_transition_requires_full_evidence_chain(self):
        normalized = validate_transition_evidence(
            load_fixture("transition-verified.json")
        )
        self.assertEqual(normalized["status"], "VERIFIED")
        self.assertEqual(
            set(normalized["evidence"]),
            {"intent_ref", "action_ref", "result_ref", "verification_ref"},
        )
        self.assertTrue(all(normalized["evidence"].values()))

    def test_verified_transition_without_result_reference_fails_closed(self):
        report = load_fixture("transition-verified.json")
        report["evidence"]["result_ref"] = None
        with self.assertRaisesRegex(
            ProofQATransitionPreflightError,
            "REFLECT requires evidence references",
        ):
            validate_transition_evidence(report)

    def test_evidence_object_must_use_exact_contract_keys(self):
        report = load_fixture("transition-verified.json")
        del report["evidence"]["action_ref"]
        with self.assertRaisesRegex(
            ProofQATransitionPreflightError,
            "must contain exactly",
        ):
            validate_transition_evidence(report)

    def test_in_progress_report_cannot_hide_issues(self):
        report = load_fixture("transition-in-progress.json")
        report["issues"] = ["commit_without_concrete_step"]
        with self.assertRaisesRegex(
            ProofQATransitionPreflightError,
            "issues require RECALIBRATE",
        ):
            validate_transition_evidence(report)

    def test_transition_id_is_safe_for_actions_summary(self):
        report = load_fixture("transition-verified.json")
        report["transition_id"] = "release/mobile\n::error::forged"
        with self.assertRaisesRegex(
            ProofQATransitionPreflightError,
            "must use only letters",
        ):
            validate_transition_evidence(report)

    def test_phase_requires_appropriate_evidence_depth(self):
        report = load_fixture("transition-in-progress.json")
        report["phase"] = "EXECUTE"
        report["next_phase"] = "VERIFY"
        with self.assertRaisesRegex(
            ProofQATransitionPreflightError,
            "EXECUTE requires evidence references",
        ):
            validate_transition_evidence(report)

    def test_ignore_mode_needs_no_report(self):
        self.assertEqual(run({"PROOFQA_TRANSITION_POLICY": "ignore"}), 0)

    def test_require_mode_loads_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transition.json"
            path.write_text(
                json.dumps(load_fixture("transition-verified.json")),
                encoding="utf-8",
            )
            result = run(
                {
                    "PROOFQA_TRANSITION_POLICY": "require-verified",
                    "PROOFQA_TRANSITION_REPORT_PATH": str(path),
                }
            )
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
