import json
import tempfile
import unittest
from pathlib import Path

from scripts.trusted_transition_reference import (
    TrustedTransitionReferenceError,
    assemble_reference,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/proofqa/transition-manifest-bundle"


class TrustedTransitionReferenceTests(unittest.TestCase):
    def test_assembly_copies_exact_source_and_writes_honest_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            result = assemble_reference(
                source_dir=SOURCE,
                output_dir=output,
                repository="safal207/ibex-agent-verification",
                source_commit="1" * 40,
                trigger_run_id=123,
                trigger_workflow="ProofQA Release Gate Action",
            )
            files = {
                path.relative_to(output).as_posix()
                for path in output.rglob("*")
                if path.is_file()
            }
            provenance = json.loads(
                (output / "producer-provenance.json").read_text()
            )

        self.assertEqual(result["status"], "ASSEMBLED")
        self.assertEqual(
            files,
            {
                "evidence/action.json",
                "evidence/intent.json",
                "evidence/result.json",
                "evidence/verification.json",
                "producer-provenance.json",
                "transition-report.json",
            },
        )
        self.assertEqual(provenance["source_commit"], "1" * 40)
        self.assertEqual(provenance["trigger"]["event"], "push")
        self.assertEqual(provenance["trigger"]["branch"], "main")
        self.assertIn(
            "not a production deployment claim",
            provenance["claim_boundary"],
        )

    def test_wrong_trigger_workflow_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                TrustedTransitionReferenceError,
                "requires ProofQA Release Gate Action",
            ):
                assemble_reference(
                    source_dir=SOURCE,
                    output_dir=Path(directory) / "bundle",
                    repository="safal207/ibex-agent-verification",
                    source_commit="1" * 40,
                    trigger_run_id=123,
                    trigger_workflow="Untrusted Workflow",
                )

    def test_output_must_not_preexist(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            output.mkdir()
            with self.assertRaisesRegex(
                TrustedTransitionReferenceError,
                "must not already exist",
            ):
                assemble_reference(
                    source_dir=SOURCE,
                    output_dir=output,
                    repository="safal207/ibex-agent-verification",
                    source_commit="1" * 40,
                    trigger_run_id=123,
                    trigger_workflow="ProofQA Release Gate Action",
                )


if __name__ == "__main__":
    unittest.main()
