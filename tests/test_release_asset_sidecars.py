import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.release_asset_sidecars import (
    ReleaseAssetSidecarError,
    main,
    verify_release_asset_sidecars,
    write_release_asset_sidecars,
)


COMMON = {
    "subject_name": "v0.9.0-cerebras-live-evidence.zip",
    "repository": "safal207/ibex-agent-verification",
    "commit": "a" * 40,
    "tag": "v0.9.0",
    "workflow": ".github/workflows/release.yml",
}


class ReleaseAssetSidecarTests(unittest.TestCase):
    def test_sidecars_are_deterministic_across_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_asset = root / "first.zip"
            second_asset = root / "second.zip"
            first_checksum = root / "first.sha256"
            second_checksum = root / "second.sha256"
            first_provenance = root / "first.provenance.json"
            second_provenance = root / "second.provenance.json"
            payload = b"same deterministic release bytes\n"
            first_asset.write_bytes(payload)
            second_asset.write_bytes(payload)

            write_release_asset_sidecars(
                asset=first_asset,
                checksum=first_checksum,
                provenance=first_provenance,
                **COMMON,
            )
            write_release_asset_sidecars(
                asset=second_asset,
                checksum=second_checksum,
                provenance=second_provenance,
                **COMMON,
            )

            self.assertEqual(first_checksum.read_bytes(), second_checksum.read_bytes())
            self.assertEqual(first_provenance.read_bytes(), second_provenance.read_bytes())

    def test_valid_sidecars_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "asset.zip"
            checksum = root / "asset.zip.sha256"
            provenance = root / "asset.zip.provenance.json"
            asset.write_bytes(b"release evidence\n")
            write_release_asset_sidecars(
                asset=asset,
                checksum=checksum,
                provenance=provenance,
                **COMMON,
            )

            result = verify_release_asset_sidecars(
                asset=asset,
                checksum=checksum,
                provenance=provenance,
                **COMMON,
            )

            self.assertEqual(result["status"], "VERIFIED")
            self.assertTrue(all(result["checks"].values()))
            record = json.loads(provenance.read_text(encoding="utf-8"))
            self.assertEqual(record["subject"]["name"], COMMON["subject_name"])
            self.assertEqual(record["release"]["commit"], COMMON["commit"])

    def test_changed_asset_invalidates_both_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "asset.zip"
            checksum = root / "asset.zip.sha256"
            provenance = root / "asset.zip.provenance.json"
            asset.write_bytes(b"original\n")
            write_release_asset_sidecars(
                asset=asset,
                checksum=checksum,
                provenance=provenance,
                **COMMON,
            )
            asset.write_bytes(b"tampered\n")

            result = verify_release_asset_sidecars(
                asset=asset,
                checksum=checksum,
                provenance=provenance,
                **COMMON,
            )

            self.assertEqual(result["status"], "METADATA_MISMATCH")
            self.assertFalse(result["checks"]["checksum_exact_match"])
            self.assertFalse(result["checks"]["provenance_exact_match"])

    def test_malformed_sidecars_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "asset.zip"
            checksum = root / "asset.zip.sha256"
            provenance = root / "asset.zip.provenance.json"
            asset.write_bytes(b"release\n")
            checksum.write_text("not-a-checksum\n", encoding="utf-8")
            provenance.write_text("{not-json}\n", encoding="utf-8")

            result = verify_release_asset_sidecars(
                asset=asset,
                checksum=checksum,
                provenance=provenance,
                **COMMON,
            )

            self.assertEqual(result["status"], "METADATA_MISMATCH")
            self.assertFalse(result["checks"]["checksum_exact_match"])
            self.assertFalse(result["checks"]["provenance_exact_match"])
            self.assertIsNotNone(result["provenance"]["parse_error"])

    def test_invalid_subject_name_and_missing_files_are_input_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "asset.zip"
            asset.write_bytes(b"release\n")
            with self.assertRaisesRegex(ReleaseAssetSidecarError, "plain file name"):
                write_release_asset_sidecars(
                    asset=asset,
                    subject_name="../asset.zip",
                    checksum=root / "asset.sha256",
                    provenance=root / "asset.json",
                    repository=COMMON["repository"],
                    commit=COMMON["commit"],
                    tag=COMMON["tag"],
                    workflow=COMMON["workflow"],
                )

            with redirect_stderr(StringIO()):
                exit_code = main(
                    [
                        "verify",
                        "--asset",
                        str(asset),
                        "--subject-name",
                        COMMON["subject_name"],
                        "--checksum",
                        str(root / "missing.sha256"),
                        "--provenance",
                        str(root / "missing.json"),
                        "--repository",
                        COMMON["repository"],
                        "--commit",
                        COMMON["commit"],
                        "--tag",
                        COMMON["tag"],
                        "--workflow",
                        COMMON["workflow"],
                    ]
                )
            self.assertEqual(exit_code, 2)

    def test_cli_verify_writes_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "asset.zip"
            checksum = root / "asset.zip.sha256"
            provenance = root / "asset.zip.provenance.json"
            report = root / "verification.json"
            asset.write_bytes(b"release\n")
            write_release_asset_sidecars(
                asset=asset,
                checksum=checksum,
                provenance=provenance,
                **COMMON,
            )

            args = [
                "verify",
                "--asset",
                str(asset),
                "--subject-name",
                COMMON["subject_name"],
                "--checksum",
                str(checksum),
                "--provenance",
                str(provenance),
                "--repository",
                COMMON["repository"],
                "--commit",
                COMMON["commit"],
                "--tag",
                COMMON["tag"],
                "--workflow",
                COMMON["workflow"],
                "--report",
                str(report),
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "VERIFIED")

            checksum.write_text("0" * 64 + "  wrong.zip\n", encoding="utf-8")
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), 1)


if __name__ == "__main__":
    unittest.main()
