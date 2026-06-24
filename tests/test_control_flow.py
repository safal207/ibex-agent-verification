import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.control_flow import (
    analyze_control_flow,
    extract_control_flow_redirects,
    main,
)
from ibex_agent_verification.ibex_trace import parse_ibex_trace_lines
from ibex_agent_verification.models import TraceValidationError


class ControlFlowEvidenceTests(unittest.TestCase):
    def parse(self, *lines):
        return parse_ibex_trace_lines(
            [f"{line}\n" for line in lines], source="control-flow.log"
        )

    def test_taken_jal_emits_redirect_and_delay_evidence(self):
        parsed = self.parse(
            "20 6 00100080 2d00006f jal x0,100350 x0=0x00000000",
            "26 9 00100350 00000093 addi x1,x0,0 x1=0x00000000",
        )
        analysis = analyze_control_flow(parsed)
        self.assertEqual(len(analysis.redirects), 1)
        redirect = analysis.redirects[0]
        self.assertEqual(redirect.redirect_kind, "direct_jump")
        self.assertEqual(redirect.from_pc, 0x00100080)
        self.assertEqual(redirect.sequential_pc, 0x00100084)
        self.assertEqual(redirect.target_pc, 0x00100350)
        self.assertEqual(redirect.delay_cycles, 2)
        self.assertEqual(redirect.to_dict()["primary_cause"], "BRANCH_REDIRECT")
        self.assertFalse(redirect.to_dict()["pipeline_flush_confirmed"])

    def test_taken_conditional_branch_is_detected(self):
        parsed = self.parse(
            "10 4 00000100 00208463 beq x1,x2,8 x1:0x1 x2:0x1",
            "14 6 00000108 00000013 addi x0,x0,0",
        )
        redirect = analyze_control_flow(parsed).redirects[0]
        self.assertEqual(redirect.redirect_kind, "conditional_branch")
        self.assertEqual(redirect.target_pc, 0x108)

    def test_not_taken_branch_is_not_reported_as_redirect(self):
        parsed = self.parse(
            "10 4 00000100 00208463 beq x1,x2,8 x1:0x1 x2:0x2",
            "12 5 00000104 00000013 addi x0,x0,0",
        )
        self.assertEqual(analyze_control_flow(parsed).redirects, ())

    def test_compressed_instruction_uses_two_byte_sequential_pc(self):
        parsed = self.parse(
            "10 4 00000100 a001 c.j 0x120",
            "12 5 00000120 0001 c.nop",
        )
        redirect = analyze_control_flow(parsed).redirects[0]
        self.assertEqual(redirect.instruction_width_bits, 16)
        self.assertEqual(redirect.sequential_pc, 0x102)

    def test_unrecognized_pc_discontinuity_does_not_invent_branch_cause(self):
        parsed = self.parse(
            "10 4 00000100 00000013 addi x0,x0,0",
            "12 5 00000200 00000013 addi x0,x0,0",
        )
        self.assertEqual(analyze_control_flow(parsed).redirects, ())

    def test_expected_cycles_validation_matches_timing_contract(self):
        parsed = self.parse(
            "10 4 00000100 0000006f jal x0,8",
            "12 5 00000108 00000013 addi x0,x0,0",
        )
        with self.assertRaisesRegex(
            TraceValidationError, "expected_cycles must be a non-negative integer"
        ):
            extract_control_flow_redirects(parsed.records, expected_cycles=-1)

    def test_cli_writes_jsonl_and_report(self):
        trace = "\n".join(
            [
                "Time Cycle PC Instr Decoded instruction",
                "20 6 00100080 2d00006f jal x0,100350 x0=0x00000000",
                "26 9 00100350 00000093 addi x1,x0,0 x1=0x00000000",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "trace_core_00000000.log"
            output = root / "redirects.jsonl"
            report = root / "report.json"
            source.write_text(trace, encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "--input",
                        str(source),
                        "--output",
                        str(output),
                        "--report",
                        str(report),
                    ]
                ),
                0,
            )

            rows = [json.loads(line) for line in output.read_text().splitlines()]
            summary = json.loads(report.read_text())

        self.assertEqual(rows[0]["primary_cause"], "BRANCH_REDIRECT")
        self.assertEqual(summary["redirects"], 1)
        self.assertEqual(summary["delayed_redirects"], 1)
        self.assertEqual(summary["pipeline_flush_claims"], 0)


if __name__ == "__main__":
    unittest.main()
