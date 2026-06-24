import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.models import TraceValidationError
from ibex_agent_verification.timing import (
    TimingSample,
    analyze_sample,
    analyze_timing,
    load_timing_jsonl,
)


class TimingAnalysisTests(unittest.TestCase):
    def sample(self, *, expected=2, end=8, signals=None):
        return TimingSample.from_raw(
            {
                "step": 25,
                "cycle_start": 0,
                "cycle_end": end,
                "expected_cycles": expected,
                "signals": signals or {},
            }
        )

    def test_memory_wait_is_primary_cause(self):
        finding = analyze_sample(
            self.sample(
                signals={
                    "pipeline_stall": True,
                    "data_req": True,
                    "data_ready": False,
                    "memory_wait_cycles": 5,
                }
            )
        )
        self.assertEqual(finding.status, "DELAY_ANOMALY")
        self.assertEqual(finding.primary_cause, "MEMORY_WAIT")
        self.assertEqual(finding.confidence, 0.95)
        self.assertIn("memory_wait_cycles=5", finding.evidence)

    def test_instruction_fetch_wait_is_primary_with_explicit_wait(self):
        finding = analyze_sample(
            self.sample(
                signals={
                    "instr_req": True,
                    "instr_ready": False,
                    "instruction_wait_cycles": 3,
                }
            )
        )
        self.assertEqual(finding.status, "DELAY_ANOMALY")
        self.assertEqual(finding.primary_cause, "INSTRUCTION_FETCH_WAIT")
        self.assertEqual(finding.confidence, 0.75)
        self.assertEqual(
            finding.evidence,
            (
                "instruction_wait_cycles=3",
                "instr_req=true",
                "instr_ready=false",
            ),
        )

    def test_instruction_request_without_wait_is_not_a_cause(self):
        finding = analyze_sample(
            self.sample(signals={"instr_req": True, "instr_ready": True})
        )
        self.assertEqual(finding.primary_cause, "UNKNOWN")
        self.assertEqual(finding.candidates, ())

    def test_memory_wait_remains_primary_over_fetch_wait(self):
        finding = analyze_sample(
            self.sample(
                signals={
                    "data_req": True,
                    "data_ready": False,
                    "memory_wait_cycles": 2,
                    "instr_req": True,
                    "instr_ready": False,
                    "instruction_wait_cycles": 1,
                }
            )
        )
        self.assertEqual(finding.primary_cause, "MEMORY_WAIT")
        self.assertEqual(finding.confidence, 0.85)
        self.assertEqual(
            [candidate.cause for candidate in finding.candidates],
            ["MEMORY_WAIT", "INSTRUCTION_FETCH_WAIT"],
        )

    def test_instruction_grant_wait_is_supported(self):
        finding = analyze_sample(
            self.sample(
                signals={
                    "instr_req": True,
                    "instr_grant": False,
                    "instruction_grant_wait_cycles": 2,
                }
            )
        )
        self.assertEqual(finding.primary_cause, "INSTRUCTION_FETCH_WAIT")
        self.assertEqual(finding.confidence, 0.75)
        self.assertIn("instruction_grant_wait_cycles=2", finding.evidence)

    def test_branch_recovery_can_be_ranked(self):
        finding = analyze_sample(
            self.sample(
                signals={
                    "branch_mispredict": True,
                    "pipeline_flush": True,
                    "branch_recovery_cycles": 2,
                }
            )
        )
        self.assertEqual(finding.primary_cause, "BRANCH_RECOVERY")
        self.assertEqual(finding.confidence, 0.99)

    def test_unknown_cause_is_not_invented(self):
        finding = analyze_sample(self.sample())
        self.assertEqual(finding.primary_cause, "UNKNOWN")
        self.assertEqual(finding.confidence, 0.0)

    def test_on_time_sample_is_not_an_anomaly(self):
        analysis = analyze_timing([self.sample(expected=2, end=2)])
        self.assertEqual(analysis.status, "ON_TIME")
        self.assertFalse(analysis.has_anomalies)

    def test_faster_sample_is_reported_without_causal_claim(self):
        finding = analyze_sample(self.sample(expected=4, end=2))
        self.assertEqual(finding.status, "FASTER_THAN_EXPECTED")
        self.assertIsNone(finding.primary_cause)

    def test_invalid_cycle_range_is_rejected(self):
        with self.assertRaises(TraceValidationError):
            TimingSample.from_raw(
                {
                    "step": 1,
                    "cycle_start": 10,
                    "cycle_end": 9,
                    "expected_cycles": 1,
                }
            )

    def test_jsonl_loader_adds_line_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.jsonl"
            path.write_text('{"step":0,"cycle_start":0}\n', encoding="utf-8")
            with self.assertRaisesRegex(TraceValidationError, r":1:"):
                load_timing_jsonl(path)


if __name__ == "__main__":
    unittest.main()
