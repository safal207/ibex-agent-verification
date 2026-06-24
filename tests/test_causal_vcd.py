import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.causal_vcd import (
    enrich_timing_rows,
    load_vcd_cycle_snapshots,
)
from ibex_agent_verification.models import TraceValidationError


def synthetic_vcd() -> str:
    return """$timescale 1ns $end
$scope module TOP $end
$scope module ibex_simple_system $end
$var wire 1 ! clk_sys $end
$var wire 1 \" timer_irq $end
$scope module u_top $end
$var wire 1 # rvfi_valid $end
$var wire 1 $ rvfi_intr $end
$var wire 1 % rvfi_trap $end
$var wire 1 & instr_req_o $end
$var wire 1 ' instr_gnt_i $end
$var wire 1 ( instr_rvalid_i $end
$var wire 1 ) data_req_o $end
$var wire 1 * data_gnt_i $end
$var wire 1 + data_rvalid_i $end
$upscope $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0\"
0#
0$
0%
0&
1'
0(
0)
1*
0+
#1
1!
#2
0!
#3
1!
1&
#4
0!
#5
1!
0&
1(
#6
0!
#7
1!
1)
0+
#8
0!
#9
1!
0)
1+
1#
0$
0%
#10
0!
#11
1!
0+
1#
1$
#12
0!
"""


class CausalVcdTests(unittest.TestCase):
    def test_extracts_rising_edges_and_resolves_pinned_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sim.vcd"
            path.write_text(synthetic_vcd(), encoding="utf-8")
            snapshots, names, missing = load_vcd_cycle_snapshots(path)

        self.assertEqual([item.time for item in snapshots], [1, 3, 5, 7, 9, 11])
        self.assertEqual(
            names["rvfi_valid"], "TOP.ibex_simple_system.u_top.rvfi_valid"
        )
        self.assertEqual(missing, [])
        self.assertTrue(snapshots[3].data_wait)
        self.assertFalse(snapshots[4].data_wait)
        self.assertTrue(snapshots[1].instruction_wait)

    def test_enriches_memory_wait_and_interrupt_without_pipeline_invention(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sim.vcd"
            path.write_text(synthetic_vcd(), encoding="utf-8")
            snapshots, _, _ = load_vcd_cycle_snapshots(path)

        metadata = [
            {"simulation_time": 1, "cycle": 1},
            {"simulation_time": 5, "cycle": 3},
            {"simulation_time": 9, "cycle": 5},
            {"simulation_time": 11, "cycle": 6},
        ]
        timing = [
            {
                "step": 1,
                "cycle_start": 1,
                "cycle_end": 3,
                "expected_cycles": 1,
                "signals": {},
            },
            {
                "step": 2,
                "cycle_start": 3,
                "cycle_end": 5,
                "expected_cycles": 1,
                "signals": {},
            },
            {
                "step": 3,
                "cycle_start": 5,
                "cycle_end": 6,
                "expected_cycles": 1,
                "signals": {},
            },
        ]

        enriched, report = enrich_timing_rows(
            timing, metadata, snapshots, waveform_source="raw/sim.fst"
        )

        self.assertEqual(enriched[0]["signals"]["instruction_wait_cycles"], 1)
        self.assertEqual(enriched[1]["signals"]["memory_wait_cycles"], 1)
        self.assertFalse(enriched[1]["signals"]["data_ready"])
        self.assertTrue(enriched[2]["signals"]["interrupt"])
        self.assertNotIn("pipeline_stall", enriched[1]["signals"])
        self.assertEqual(report["alignment_ratio"], 1.0)
        self.assertEqual(report["samples_with_memory_wait"], 1)
        self.assertEqual(report["samples_with_interrupt"], 1)

    def test_missing_required_signal_fails_closed(self):
        broken = synthetic_vcd().replace(
            "$var wire 1 + data_rvalid_i $end\n", ""
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.vcd"
            path.write_text(broken, encoding="utf-8")
            with self.assertRaisesRegex(TraceValidationError, "data_rvalid"):
                load_vcd_cycle_snapshots(path)

    def test_cli_outputs_report_and_enriched_jsonl(self):
        from ibex_agent_verification.causal_vcd import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vcd = root / "sim.vcd"
            metadata = root / "metadata.jsonl"
            timing = root / "timing.jsonl"
            output = root / "timing-causal.jsonl"
            report = root / "causal-report.json"
            vcd.write_text(synthetic_vcd(), encoding="utf-8")
            metadata.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"simulation_time": 1, "cycle": 1},
                        {"simulation_time": 5, "cycle": 3},
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            timing.write_text(
                json.dumps(
                    {
                        "step": 1,
                        "cycle_start": 1,
                        "cycle_end": 3,
                        "expected_cycles": 1,
                        "signals": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--vcd",
                    str(vcd),
                    "--metadata",
                    str(metadata),
                    "--timing",
                    str(timing),
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(report.read_text())["status"], "ENRICHED")


if __name__ == "__main__":
    unittest.main()
