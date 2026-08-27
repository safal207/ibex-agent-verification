"""Cross-runtime ordering tests for semantic sets."""

import unittest

from ibex_agent_verification.action_chain import _sorted_unique_strings


class SemanticSetOrderingTests(unittest.TestCase):
    """Lock unsigned UTF-8 bytewise ordering."""

    def test_utf8_order_differs_from_utf16_order(self):
        """Supplementary text must sort by UTF-8 bytes, not UTF-16 units."""

        supplementary = chr(0x10000)
        private_use = chr(0xE000)
        values = [supplementary, private_use]
        expected = [private_use, supplementary]
        self.assertEqual(_sorted_unique_strings(values, "test"), expected)


if __name__ == "__main__":
    unittest.main()
