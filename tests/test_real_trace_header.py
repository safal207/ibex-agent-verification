import unittest

from ibex_agent_verification.ibex_trace import parse_ibex_trace_lines


class RealIbexTraceHeaderTests(unittest.TestCase):
    def test_real_verilator_header_and_memory_row_parse(self):
        result = parse_ibex_trace_lines(
            [
                (
                    "Time\tCycle\tPC\tInsn\tDecoded instruction\t"
                    "Register and memory contents\n"
                ),
                (
                    "26548\t13270\t001003c6\t0062a023\tsw\tx6,0(x5)\t"
                    "x5:0x00020008 x6:0x00000001 "
                    "PA:0x00020008 store:0x00000001\n"
                ),
            ],
            source="real-verilator.log",
        )

        self.assertEqual(result.header_lines, 1)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].mnemonic, "sw")
        self.assertEqual(
            result.records[0].memory,
            {"address": 0x00020008, "write_value": 0x00000001},
        )


if __name__ == "__main__":
    unittest.main()
