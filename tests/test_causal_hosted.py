import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.causal_hosted import (
    _resolved_code_groups,
    _restore_equivalent_signal_aliases,
    enrich_hosted_waveform,
)
from ibex_agent_verification.causal_vcd import load_vcd_cycle_snapshots


def hosted_shape_vcd() -> str:
    return """$timescale 1ps $end
$scope module TOP $end
$scope module ibex_simple_system $end
$var wire 1 ! clk_sys $end
$var wire 1 \" timer_irq $end
$scope module u_top $end
$var wire 1 # rvfi_valid $end
$var wire 1 $ rvfi_intr $end
$var wire 1 % rvfi_trap $end
$var wire 1 & instr_req_o $end
$var wire 1 & instr_gnt_i $end
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
0(
0)
1*
0+
#1
1!
1#
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
#10
0!
#11
1!
1#
1$
#12
0!
"""


class HostedCausalAdapterTests(unittest.TestCase):
    def test_restores_shared_vcd_code_and_infers_minus_one_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sim.vcd"
            path.write_text(hosted_shape_vcd(), encoding="utf-8")
            snapshots, _, _ = load_vcd_cycle_snapshots(path)
            groups = _resolved_code_groups(path)
            restored = _restore_equivalent_signal_aliases(snapshots, groups)

        self.assertIn(("instr_req", "instr_gnt"), groups)
        self.assertEqual(restored[1].values["instr_req"], 1)
        self.assertEqual(restored[1].values["instr_gnt"], 1)

        metadata = [
            {"simulation_time": 2, "cycle": 1},
            {"simulation_time": 6, "cycle": 3},
            {"simulation_time": 10, "cycle": 5},
            {"simulation_time": 12, "cycle": 6},
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

        enriched, report = enrich_hosted_waveform(
            timing, metadata, restored, waveform_source="raw/sim.fst"
        )

        self.assertEqual(report["alignment_ratio"], 1.0)
        self.assertEqual(report["retirement_time_offset"], -1)
        evidence = enriched[0]["signals"]["waveform_evidence"]
        self.assertEqual(evidence["trace_time_start"], 2)
        self.assertEqual(evidence["waveform_time_start_exclusive"], 1)
        self.assertEqual(evidence["waveform_time_offset"], -1)


if __name__ == "__main__":
    unittest.main()
