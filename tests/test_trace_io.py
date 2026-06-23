import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.models import TraceValidationError
from ibex_agent_verification.trace_io import load_jsonl


class TraceIoTests(unittest.TestCase):
    def test_hex_values_are_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(
                '{"step":0,"pc":"0x10","instruction":"0x13","register_write":null}\n',
                encoding="utf-8",
            )
            event = load_jsonl(path)[0]
            self.assertEqual(event.pc, 16)
            self.assertEqual(event.instruction, 19)

    def test_non_increasing_steps_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(
                '{"step":0,"pc":0,"instruction":0}\n'
                '{"step":0,"pc":4,"instruction":0}\n',
                encoding="utf-8",
            )
            with self.assertRaises(TraceValidationError):
                load_jsonl(path)


if __name__ == "__main__":
    unittest.main()
