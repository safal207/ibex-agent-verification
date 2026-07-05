from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ibex_agent_verification.human_review_receipts import (
    evaluate_human_review_gate,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ibex_human_review_gate.py"
SCHEMA = ROOT / "schemas/human_review_gate_v1.schema.json"
HEAD = "a" * 40


def _load_cli_module():
    spec = importlib.util.spec_from_file_location(
        "ibex_human_review_gate_cli", SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load human review gate CLI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HumanReviewGateRegressionTests(unittest.TestCase):
    def test_noncanonical_repository_fails_closed(self) -> None:
        gate = evaluate_human_review_gate(
            repository="bad owner/repo",
            pull_request_number=1,
            current_head=HEAD,
            author="author",
            reviews=[],
            observed_at="2026-07-05T18:00:00Z",
            policy_version="review-policy-v1",
        )
        self.assertEqual(gate["status"], "NON_RECOMPUTABLE")
        self.assertEqual(gate["reasons"][0]["code"], "INVALID_INPUT")
        self.assertFalse(gate["merge_authorized"])

    def test_malformed_reviews_json_still_writes_gate_artifact(self) -> None:
        cli = _load_cli_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviews = root / "reviews.json"
            output = root / "gate.json"
            reviews.write_text("{not-json", encoding="utf-8")
            argv = [
                str(SCRIPT),
                "--repository", "owner/repo",
                "--pull-request", "1",
                "--head", HEAD,
                "--author", "author",
                "--reviews", str(reviews),
                "--observed-at", "2026-07-05T18:00:00Z",
                "--policy-version", "review-policy-v1",
                "--output", str(output),
            ]
            with patch.object(sys, "argv", argv):
                exit_code = cli.main()
            gate = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(gate["status"], "NON_RECOMPUTABLE")
        self.assertEqual(gate["reasons"][0]["code"], "INVALID_INPUT")
        self.assertFalse(gate["merge_authorized"])

    def test_schema_binds_derived_fields_to_every_status(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        branches = {
            item["if"]["properties"]["status"]["const"]: item["then"][
                "properties"
            ]
            for item in schema["allOf"]
        }
        self.assertEqual(set(branches), {
            "SATISFIED",
            "REQUIRED_EXTERNAL",
            "NON_RECOMPUTABLE",
        })
        self.assertEqual(branches["SATISFIED"]["gate_satisfied"]["const"], True)
        self.assertEqual(branches["SATISFIED"]["blocking"]["const"], False)
        self.assertEqual(
            branches["REQUIRED_EXTERNAL"]["permitted_next_transition"]["const"],
            "REQUEST_BINDING_HUMAN_REVIEW",
        )
        self.assertEqual(
            branches["NON_RECOMPUTABLE"]["permitted_next_transition"]["const"],
            "BLOCK_AND_REPAIR_EVIDENCE",
        )


if __name__ == "__main__":
    unittest.main()
