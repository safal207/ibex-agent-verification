import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.production_transition_source import (
    ProductionTransitionSourceError,
    validate_production_transition_source,
    write_validation_report,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/proofqa/production-transition-source"
EXPECTED = {
    "expected_repository": "safal207/ibex-agent-verification",
    "expected_commit": "a" * 40,
    "expected_workflow": ".github/workflows/deploy-production.yml",
    "expected_run_id": 987654321,
    "expected_run_attempt": 2,
    "expected_event": "push",
    "expected_branch": "main",
    "expected_environment": "production",
    "expected_destination_id": "github-environment:production",
}


def validate(source: Path, **overrides):
    return validate_production_transition_source(
        source_dir=source,
        **{**EXPECTED, **overrides},
    )


def rewrite(path: Path, mutate):
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class ProductionTransitionSourceTests(unittest.TestCase):
    def copy_source(self, directory: str) -> Path:
        destination = Path(directory) / "source"
        shutil.copytree(SOURCE, destination)
        return destination

    def test_valid_source_is_bound_to_expected_metadata(self):
        result = validate(SOURCE)

        self.assertEqual(result["status"], "VALIDATED")
        self.assertEqual(result["files_checked"], 6)
        self.assertEqual(result["source_commit"], "a" * 40)
        self.assertRegex(result["source_set_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            [item["path"] for item in result["files"]],
            [
                "evidence/action.json",
                "evidence/intent.json",
                "evidence/result.json",
                "evidence/verification.json",
                "source-provenance.json",
                "transition-report.json",
            ],
        )

    def test_validation_is_deterministic(self):
        self.assertEqual(validate(SOURCE), validate(SOURCE))

    def test_expected_commit_mismatch_is_rejected(self):
        with self.assertRaisesRegex(
            ProductionTransitionSourceError,
            "source provenance source_commit mismatch",
        ):
            validate(SOURCE, expected_commit="c" * 40)

    def test_extra_source_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            (source / "unexpected.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "production source layout mismatch",
            ):
                validate(source)

    def test_symlinked_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            intent = source / "evidence/intent.json"
            intent.unlink()
            intent.symlink_to("result.json")
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "contains a symlink",
            ):
                validate(source)

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            (source / "source-provenance.json").write_text(
                '{"schema_version":1,"schema_version":1}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "duplicate key: schema_version",
            ):
                validate(source)

    def test_transition_role_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            rewrite(
                source / "transition-report.json",
                lambda payload: payload["evidence"].__setitem__(
                    "result_ref", "manifest:evidence/verification.json"
                ),
            )
            with self.assertRaisesRegex(
                (ProductionTransitionSourceError, ValueError),
                "distinct file|result_ref mismatch",
            ):
                validate(source)

    def test_action_run_identity_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            rewrite(
                source / "evidence/action.json",
                lambda payload: payload["deployment"].__setitem__("run_attempt", 3),
            )
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "action evidence deployment mismatch",
            ):
                validate(source)

    def test_result_subject_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            rewrite(
                source / "evidence/result.json",
                lambda payload: payload.__setitem__(
                    "subject_digest", "sha256:" + "c" * 64
                ),
            )
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "result evidence subject_digest mismatch",
            ):
                validate(source)

    def test_observed_destination_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            rewrite(
                source / "evidence/verification.json",
                lambda payload: payload["observed_destination"].__setitem__(
                    "identity", "github-environment:staging"
                ),
            )
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "observed_destination mismatch",
            ):
                validate(source)

    def test_claim_boundary_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            rewrite(
                source / "transition-report.json",
                lambda payload: payload.__setitem__(
                    "claim_boundary", "A different and unbound claim."
                ),
            )
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "transition claim_boundary mismatch",
            ):
                validate(source)

    def test_validation_report_must_be_outside_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            result = validate(source)
            with self.assertRaisesRegex(
                ProductionTransitionSourceError,
                "outside the production source directory",
            ):
                write_validation_report(
                    path=source / "source-validation.json",
                    payload=result,
                    source_dir=source,
                )

    def test_validation_report_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.copy_source(directory)
            result = validate(source)
            report = Path(directory) / "reports/source-validation.json"
            write_validation_report(path=report, payload=result, source_dir=source)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), result)


if __name__ == "__main__":
    unittest.main()
