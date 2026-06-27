import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ibex_agent_verification.cli import main
from ibex_agent_verification.transition_phase import (
    TransitionPhaseError,
    evaluate_transition,
)


def verified_record() -> dict:
    return {
        "schema_version": 1,
        "transition_id": "checkout.payment-recovery/731",
        "time": {
            "observed_before_ns": 100,
            "intent_declared_ns": 120,
            "commit_ns": 140,
            "action_started_ns": 160,
            "result_observed_ns": 220,
            "evaluated_ns": 240,
            "deadline_ns": 300,
        },
        "intention": {
            "intent_id": "resume-confirmed-payment",
            "statement": "Recover the committed payment without submitting it again.",
            "action": "Fetch payment 731 and render the server-confirmed state.",
            "expected_result": "Payment 731 is shown as paid exactly once.",
            "stopping_condition": "The paid state is verified and no retry is emitted.",
        },
        "space": {
            "origin": "mobile.checkout.submitting",
            "boundary": "process-restart-and-server-reconciliation",
            "destination": "mobile.payment.success/731",
        },
        "evidence": {
            "intent_ref": "sha256:intent-731",
            "action_ref": "trace:payment-get-731",
            "result_ref": "response:payment-731-paid",
            "verification_ref": "assertion:no-duplicate-submit",
        },
        "verification": {
            "result_matches_expectation": True,
            "destination_observed": True,
            "stopping_condition_met": True,
        },
    }


class TransitionPhaseTests(unittest.TestCase):
    def test_verified_transition_converges_across_all_three_axes(self):
        result = evaluate_transition(verified_record())
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["phase"], "REFLECT")
        self.assertEqual(result["next_phase"], "CONTINUE")
        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {axis["status"] for axis in result["axes"].values()},
            {"PASS"},
        )
        self.assertEqual(result["axes"]["time"]["t_minus_ns"], 100)
        self.assertEqual(result["axes"]["time"]["t_zero_ns"], 140)
        self.assertEqual(result["axes"]["time"]["t_plus_ns"], 220)

    def test_declared_intent_without_concrete_step_remains_expand(self):
        record = verified_record()
        record["time"].update(
            {
                "commit_ns": None,
                "action_started_ns": None,
                "result_observed_ns": None,
            }
        )
        record["intention"].update(
            {
                "action": None,
                "expected_result": None,
                "stopping_condition": None,
            }
        )
        record["space"].update({"boundary": None, "destination": None})
        record["evidence"].update(
            {
                "action_ref": None,
                "result_ref": None,
                "verification_ref": None,
            }
        )
        record["verification"].update(
            {
                "result_matches_expectation": None,
                "destination_observed": None,
                "stopping_condition_met": None,
            }
        )

        result = evaluate_transition(record)
        self.assertEqual(result["status"], "IN_PROGRESS")
        self.assertEqual(result["phase"], "EXPAND")
        self.assertEqual(result["next_phase"], "COMMIT")
        self.assertEqual(result["axes"]["intention"]["status"], "WAIT")
        self.assertEqual(result["axes"]["space"]["status"], "WAIT")

    def test_claimed_commit_without_concrete_step_recalibrates(self):
        record = verified_record()
        record["intention"]["action"] = None
        record["evidence"].update(
            {
                "action_ref": None,
                "result_ref": None,
                "verification_ref": None,
            }
        )
        record["verification"].update(
            {
                "result_matches_expectation": None,
                "destination_observed": None,
                "stopping_condition_met": None,
            }
        )

        result = evaluate_transition(record)
        self.assertEqual(result["status"], "RECALIBRATE")
        self.assertEqual(result["phase"], "RECALIBRATE")
        self.assertIn("commit_without_concrete_step", result["issues"])
        self.assertEqual(result["axes"]["intention"]["status"], "BLOCK")

    def test_commit_cannot_precede_declared_intention(self):
        record = verified_record()
        record["time"]["intent_declared_ns"] = 150
        record["time"]["commit_ns"] = 140
        with self.assertRaisesRegex(TransitionPhaseError, "must not precede"):
            evaluate_transition(record)

    def test_execution_requires_prior_commit(self):
        record = verified_record()
        record["time"]["commit_ns"] = None
        with self.assertRaisesRegex(TransitionPhaseError, "requires time.commit_ns"):
            evaluate_transition(record)

    def test_orphaned_action_reference_recalibrates(self):
        record = verified_record()
        record["time"]["action_started_ns"] = None
        record["time"]["result_observed_ns"] = None
        record["evidence"]["result_ref"] = None
        record["evidence"]["verification_ref"] = None
        record["verification"] = {
            "result_matches_expectation": None,
            "destination_observed": None,
            "stopping_condition_met": None,
        }

        result = evaluate_transition(record)
        self.assertEqual(result["status"], "RECALIBRATE")
        self.assertIn("execution_without_action_evidence", result["issues"])
        self.assertEqual(result["axes"]["intention"]["status"], "BLOCK")

    def test_late_result_recalibrates_time_axis(self):
        record = verified_record()
        record["time"]["deadline_ns"] = 200
        result = evaluate_transition(record)
        self.assertEqual(result["status"], "RECALIBRATE")
        self.assertEqual(result["axes"]["time"]["status"], "BLOCK")

    def test_unobserved_destination_recalibrates_only_relevant_axes(self):
        record = verified_record()
        record["verification"]["destination_observed"] = False
        result = evaluate_transition(record)
        self.assertEqual(result["status"], "RECALIBRATE")
        self.assertEqual(result["axes"]["space"]["status"], "BLOCK")
        self.assertEqual(result["axes"]["time"]["status"], "PASS")
        self.assertEqual(result["axes"]["intention"]["status"], "PASS")

    def test_destination_claim_without_verification_reference_never_passes(self):
        record = verified_record()
        record["evidence"]["verification_ref"] = None
        result = evaluate_transition(record)
        self.assertEqual(result["status"], "RECALIBRATE")
        self.assertIn(
            "verification_claim_without_complete_evidence",
            result["issues"],
        )
        self.assertEqual(result["axes"]["space"]["status"], "BLOCK")

    def test_destination_cannot_equal_origin(self):
        record = verified_record()
        record["space"]["destination"] = record["space"]["origin"]
        with self.assertRaisesRegex(TransitionPhaseError, "must differ"):
            evaluate_transition(record)

    def test_exact_schema_rejects_untracked_fields(self):
        record = verified_record()
        record["intention"]["hidden_motive"] = "invented"
        with self.assertRaisesRegex(TransitionPhaseError, "extra"):
            evaluate_transition(record)

    def test_partial_intent_claim_recalibrates_instead_of_fabricating_intent(self):
        record = verified_record()
        record["intention"]["statement"] = None
        result = evaluate_transition(record)
        self.assertEqual(result["status"], "RECALIBRATE")
        self.assertIn(
            "intent_claim_without_complete_declaration",
            result["issues"],
        )

    def test_orphaned_action_text_without_intent_declaration_recalibrates(self):
        record = verified_record()
        record["intention"].update(
            {
                "intent_id": None,
                "statement": None,
            }
        )
        record["time"].update(
            {
                "intent_declared_ns": None,
                "commit_ns": None,
                "action_started_ns": None,
                "result_observed_ns": None,
            }
        )
        record["evidence"].update(
            {
                "intent_ref": None,
                "action_ref": None,
                "result_ref": None,
                "verification_ref": None,
            }
        )
        record["verification"] = {
            "result_matches_expectation": None,
            "destination_observed": None,
            "stopping_condition_met": None,
        }

        result = evaluate_transition(record)
        self.assertEqual(result["status"], "RECALIBRATE")
        self.assertIn(
            "intent_claim_without_complete_declaration",
            result["issues"],
        )

    def test_cli_writes_verified_report_and_uses_stable_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "transition.json"
            report = root / "verification.json"
            source.write_text(json.dumps(verified_record()), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = main(
                    [
                        "verify-transition-phase",
                        "--record",
                        str(source),
                        "--report",
                        str(report),
                    ]
                )
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "VERIFIED")
        self.assertEqual(payload["phase"], "REFLECT")

    def test_cli_refuses_to_overwrite_source_record(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "transition.json"
            original = json.dumps(verified_record(), sort_keys=True)
            source.write_text(original, encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = main(
                    [
                        "verify-transition-phase",
                        "--record",
                        str(source),
                        "--report",
                        str(source),
                    ]
                )
            observed = json.loads(source.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 2)
        self.assertEqual(observed, json.loads(original))


if __name__ == "__main__":
    unittest.main()
