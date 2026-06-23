import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.ibex_trace import (
    load_ibex_trace,
    parse_ibex_trace_lines,
    records_to_timing_dicts,
    write_architectural_jsonl,
    write_metadata_jsonl,
    write_timing_jsonl,
)
from ibex_agent_verification.models import TraceValidationError
from ibex_agent_verification.timing import TimingSample, analyze_timing

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "ibex_tracer"
    / "official_sample_022f0840.log"
)


class IbexTraceParserTests(unittest.TestCase):
    def test_official_documented_sample_parses(self):
        result = load_ibex_trace(FIXTURE)
        self.assertEqual(len(result.records), 5)
        self.assertEqual(result.header_lines, 1)
        self.assertEqual(result.records[0].cycle, 61)
        self.assertEqual(result.records[-1].cycle, 67)
        self.assertEqual(len(result.source_sha256), 64)

    def test_real_verilator_insn_header_parses(self):
        result = parse_ibex_trace_lines(
            [
                (
                    "Time\tCycle\tPC\tInsn\tDecoded instruction\t"
                    "Register and memory contents\n"
                ),
                (
                    "20\t6\t00100080\t2d00006f\tjal\tx0,100350\t"
                    "x0=0x00000000\n"
                ),
                (
                    "22\t7\t00100350\t00000093\taddi\tx1,x0,0\t"
                    "x0:0x00000000 x1=0x00000000\n"
                ),
            ],
            source="real-verilator.log",
        )
        self.assertEqual(result.header_lines, 1)
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0].mnemonic, "jal")
        self.assertEqual(result.records[1].register_write.name, "x1")

    def test_compressed_and_uncompressed_widths_are_preserved(self):
        records = load_ibex_trace(FIXTURE).records
        self.assertEqual(records[0].instruction_width_bits, 16)
        self.assertEqual(records[1].instruction_width_bits, 32)
        self.assertEqual(records[0].instruction, 0x4481)
        self.assertEqual(records[1].instruction, 0x00008437)

    def test_register_reads_and_write_are_extracted(self):
        record = load_ibex_trace(FIXTURE).records[2]
        self.assertEqual(record.decoded, "addi    x8,x8,-1")
        self.assertEqual(record.register_reads[0].name, "x8")
        self.assertEqual(record.register_reads[0].value, 0x8000)
        self.assertEqual(record.register_write.name, "x8")
        self.assertEqual(record.register_write.value, 0x7FFF)

    def test_memory_evidence_is_extracted_without_inventing_size(self):
        record = load_ibex_trace(FIXTURE).records[-1]
        self.assertEqual(
            record.memory,
            {
                "address": 0x200C,
                "read_value": 0xFFFFFFFF,
                "write_value": 0,
            },
        )
        self.assertNotIn("size", record.memory)

    def test_architectural_jsonl_has_comparator_shape(self):
        result = load_ibex_trace(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "trace.jsonl"
            write_architectural_jsonl(result, target)
            rows = [json.loads(line) for line in target.read_text().splitlines()]
        self.assertEqual(rows[0]["step"], 0)
        self.assertEqual(rows[0]["pc"], 0x150)
        self.assertEqual(
            rows[0]["register_write"], {"name": "x9", "value": 0}
        )
        self.assertIsNone(rows[0]["trap"])

    def test_metadata_preserves_cycle_width_and_decoded_instruction(self):
        result = load_ibex_trace(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "metadata.jsonl"
            write_metadata_jsonl(result, target)
            rows = [json.loads(line) for line in target.read_text().splitlines()]
        self.assertEqual(rows[0]["cycle"], 61)
        self.assertEqual(rows[0]["instruction_width_bits"], 16)
        self.assertEqual(rows[0]["decoded"], "c.li    x9,0")
        self.assertEqual(rows[0]["source_line"], 2)

    def test_timing_conversion_detects_commit_gap_without_claiming_wait(self):
        samples = records_to_timing_dicts(load_ibex_trace(FIXTURE).records)
        self.assertEqual(len(samples), 4)
        last = samples[-1]
        self.assertEqual(last["cycle_start"], 64)
        self.assertEqual(last["cycle_end"], 67)
        self.assertEqual(last["expected_cycles"], 1)
        self.assertTrue(last["signals"]["memory_access"])
        self.assertNotIn("memory_wait_cycles", last["signals"])
        self.assertNotIn("data_ready", last["signals"])

        analysis = analyze_timing(
            [TimingSample.from_raw(sample) for sample in samples]
        )
        self.assertEqual(analysis.findings[-1].primary_cause, "UNKNOWN")
        self.assertEqual(analysis.findings[-1].confidence, 0.0)

    def test_long_latency_mnemonic_becomes_instruction_evidence(self):
        result = parse_ibex_trace_lines(
            [
                "1 1 00000100 00000013 addi x0,x0,0\n",
                (
                    "9 8 00000104 0220c0b3 div x1,x1,x2 "
                    "x1:0x8 x2:0x2 x1=0x4\n"
                ),
            ]
        )
        sample = records_to_timing_dicts(result.records)[0]
        self.assertEqual(sample["signals"]["instruction_class"], "div")

    def test_malformed_line_fails_with_context(self):
        with self.assertRaisesRegex(TraceValidationError, r"demo.log:line 1"):
            parse_ibex_trace_lines(
                ["this is not a trace\n"], source="demo.log"
            )

    def test_non_increasing_cycles_are_rejected(self):
        with self.assertRaisesRegex(
            TraceValidationError, "cycle must increase strictly"
        ):
            parse_ibex_trace_lines(
                [
                    "1 2 00000100 0013 c.nop\n",
                    "2 2 00000102 0013 c.nop\n",
                ]
            )

    def test_timing_writer_outputs_jsonl(self):
        result = load_ibex_trace(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "timing.jsonl"
            write_timing_jsonl(result, target)
            rows = [json.loads(line) for line in target.read_text().splitlines()]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["cycle_end"], 67)


if __name__ == "__main__":
    unittest.main()
