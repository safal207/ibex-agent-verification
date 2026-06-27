import json
import unittest
from pathlib import Path

from ibex_agent_verification.qa_scorecard import build_reliability_scorecard
from scripts.proofqa_gate_v3 import (
    GatePolicyV3,
    ProofQAGateV3Error,
    evaluate_gate,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/proofqa"


def task_report(
    task_id: str,
    *,
    duration_ms: float,
    ttft_ms: float | None,
    generation_ms: float | None,
    status: str = "PASS",
    inference_status: str = "COMPLETE",
    http_status: int = 200,
) -> dict:
    return {
        "task_id": task_id,
        "status": status,
        "inference_status": inference_status,
        "http_status": http_status,
        "score": {"earned": 5 if status == "PASS" else 0, "possible": 5},
        "timing": {
            "duration_ms": duration_ms,
            "time_to_first_output_ms": ttft_ms,
            "generation_ms": generation_ms,
        },
    }


def policy(**overrides) -> GatePolicyV3:
    values = {
        "min_end_to_end": 90.0,
        "min_answer_correctness": 90.0,
        "min_completion_reliability": 95.0,
        "min_provider_reliability": 95.0,
        "warn_margin": 3.0,
        "max_p95_duration_ms": 1000.0,
        "time_warn_margin_ms": 250.0,
        "unknown_metric_policy": "block",
        "fail_on": "block",
        "policy_name": "time-test",
    }
    values.update(overrides)
    return GatePolicyV3(**values)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ProofQATimeAxisTests(unittest.TestCase):
    def test_scorecard_builds_deterministic_client_timing_distributions(self):
        scorecard = build_reliability_scorecard(
            [
                task_report("a", duration_ms=100.0, ttft_ms=80.0, generation_ms=20.0),
                task_report("b", duration_ms=200.0, ttft_ms=150.0, generation_ms=50.0),
                task_report("c", duration_ms=300.0, ttft_ms=250.0, generation_ms=50.0),
                task_report("d", duration_ms=400.0, ttft_ms=350.0, generation_ms=50.0),
                task_report("e", duration_ms=500.0, ttft_ms=450.0, generation_ms=50.0),
            ]
        )
        time_axis = scorecard["time_performance"]
        self.assertEqual(scorecard["schema_version"], 2)
        self.assertEqual(time_axis["clock"], "client_monotonic")
        self.assertEqual(
            time_axis["successful_requests"]["duration_ms"],
            {
                "count": 5,
                "minimum": 100.0,
                "p50": 300.0,
                "p95": 480.0,
                "maximum": 500.0,
            },
        )
        self.assertEqual(
            time_axis["successful_requests"]["time_to_first_output_ms"]["p95"],
            430.0,
        )

    def test_provider_failure_is_visible_but_excluded_from_success_latency(self):
        scorecard = build_reliability_scorecard(
            [
                task_report("ok", duration_ms=900.0, ttft_ms=800.0, generation_ms=100.0),
                task_report(
                    "quota",
                    duration_ms=20.0,
                    ttft_ms=None,
                    generation_ms=None,
                    status="INFERENCE_FAILED",
                    inference_status="REQUEST_FAILED",
                    http_status=429,
                ),
            ]
        )
        time_axis = scorecard["time_performance"]
        self.assertEqual(time_axis["all_observed_requests"]["count"], 2)
        self.assertEqual(
            time_axis["successful_requests"]["duration_ms"]["count"],
            1,
        )
        self.assertEqual(
            time_axis["successful_requests"]["duration_ms"]["p95"],
            900.0,
        )
        self.assertEqual(time_axis["provider_failed_requests_excluded"], 1)

    def test_time_policy_pass_warn_and_block(self):
        passed = evaluate_gate(
            summary=load_fixture("summary-time-pass.json"),
            policy=policy(),
        )
        warned = evaluate_gate(
            summary=load_fixture("summary-time-warn.json"),
            policy=policy(),
        )
        blocked = evaluate_gate(
            summary=load_fixture("summary-time-block.json"),
            policy=policy(),
        )
        self.assertEqual(passed["decision"], "PASS")
        self.assertEqual(warned["decision"], "WARN")
        self.assertEqual(blocked["decision"], "BLOCK")
        self.assertTrue(blocked["should_fail"])
        time_finding = next(
            finding
            for finding in blocked["findings"]
            if finding["axis"] == "time_performance"
        )
        self.assertEqual(time_finding["actual"], 1200.0)
        self.assertEqual(time_finding["direction"], "maximum")

    def test_time_gate_is_disabled_by_zero_without_breaking_v2(self):
        legacy_v2 = json.loads(
            (FIXTURES / "summary-pass.json").read_text(encoding="utf-8")
        )
        result = evaluate_gate(
            summary=legacy_v2,
            policy=policy(max_p95_duration_ms=0.0),
        )
        self.assertEqual(result["decision"], "PASS")
        time_finding = next(
            finding
            for finding in result["findings"]
            if finding["axis"] == "time_performance"
        )
        self.assertFalse(time_finding["enabled"])
        self.assertIsNone(result["metrics"]["p95_duration_ms"])

    def test_v2_with_enabled_time_gate_follows_unknown_policy(self):
        legacy_v2 = json.loads(
            (FIXTURES / "summary-pass.json").read_text(encoding="utf-8")
        )
        blocked = evaluate_gate(summary=legacy_v2, policy=policy())
        warned = evaluate_gate(
            summary=legacy_v2,
            policy=policy(unknown_metric_policy="warn"),
        )
        self.assertEqual(blocked["decision"], "BLOCK")
        self.assertEqual(warned["decision"], "WARN")

    def test_v3_requires_time_schema_and_finite_values(self):
        malformed = load_fixture("summary-time-pass.json")
        malformed["scorecard"]["schema_version"] = 1
        with self.assertRaisesRegex(ProofQAGateV3Error, "schema_version must equal 2"):
            evaluate_gate(summary=malformed, policy=policy())

        invalid = load_fixture("summary-time-pass.json")
        invalid["scorecard"]["time_performance"]["successful_requests"][
            "duration_ms"
        ]["p95"] = -1
        with self.assertRaisesRegex(ProofQAGateV3Error, "must be from 0"):
            evaluate_gate(summary=invalid, policy=policy())


if __name__ == "__main__":
    unittest.main()
