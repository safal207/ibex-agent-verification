import unittest

from ibex_agent_verification.comparator import compare_traces
from ibex_agent_verification.models import TraceEvent, TraceValidationError


class ComparatorTests(unittest.TestCase):
    def event(self, *, step=0, pc="0x100080", instruction="0x13", value="0x1"):
        return TraceEvent.from_raw(
            {
                "step": step,
                "pc": pc,
                "instruction": instruction,
                "register_write": {"name": "x1", "value": value},
                "memory": None,
                "trap": None,
            }
        )

    def test_equal_traces_match(self):
        result = compare_traces([self.event()], [self.event()])
        self.assertTrue(result.matches)
        self.assertEqual(result.status, "MATCH")

    def test_register_difference_is_reported(self):
        result = compare_traces([self.event(value="0x1")], [self.event(value="0x2")])
        self.assertFalse(result.matches)
        self.assertEqual(result.first_mismatch_index, 0)
        self.assertIn("register_write", result.differences)

    def test_length_difference_is_reported(self):
        result = compare_traces([self.event()], [])
        self.assertEqual(result.differences["trace_length"]["expected"], 1)
        self.assertEqual(result.differences["trace_length"]["actual"], 0)

    def test_invalid_register_is_rejected(self):
        with self.assertRaises(TraceValidationError):
            TraceEvent.from_raw(
                {
                    "step": 0,
                    "pc": 0,
                    "instruction": 0,
                    "register_write": {"name": "x32", "value": 0},
                }
            )


if __name__ == "__main__":
    unittest.main()
