from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HumanReviewSchemaParityTests(unittest.TestCase):
    def test_packaged_schema_matches_repository_schema(self) -> None:
        repository_schema = ROOT / "schemas/human_review_gate_v1.schema.json"
        packaged_schema = (
            ROOT
            / "src/ibex_agent_verification/schemas/human_review_gate_v1.schema.json"
        )
        self.assertEqual(
            json.loads(repository_schema.read_text(encoding="utf-8")),
            json.loads(packaged_schema.read_text(encoding="utf-8")),
        )


if __name__ == "__main__":
    unittest.main()
