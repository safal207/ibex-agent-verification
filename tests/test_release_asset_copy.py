import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.verify_release_asset_copy import (
    ReleaseAssetCopyError,
    main,
    verify_release_asset_copy,
)


class ReleaseAssetCopyTests(unittest.TestCase):
    def test_matching_files_are_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.zip"
            actual = root / "downloaded.zip"
            payload = b"deterministic-release-asset\n"
            expected.write_bytes(payload)
            actual.write_bytes(payload)

            result = verify_release_asset_copy(expected, actual)

        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["bytes_equal"])
        self.assertEqual(result["expected"]["sha256"], result["actual"]["sha256"])
        self.assertEqual(result["expected"]["size_bytes"], len(payload))

    def test_changed_download_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.zip"
            actual = root / "downloaded.zip"
            expected.write_bytes(b"expected\n")
            actual.write_bytes(b"tampered\n")

            result = verify_release_asset_copy(expected, actual)

        self.assertEqual(result["status"], "INTEGRITY_MISMATCH")
        self.assertFalse(result["bytes_equal"])
        self.assertNotEqual(result["expected"]["sha256"], result["actual"]["sha256"])

    def test_missing_copy_is_an_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.zip"
            expected.write_bytes(b"asset\n")
            with self.assertRaisesRegex(ReleaseAssetCopyError, "actual release asset"):
                verify_release_asset_copy(expected, root / "missing.zip")

    def test_cli_exit_codes_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.zip"
            actual = root / "downloaded.zip"
            report = root / "verification.json"
            expected.write_bytes(b"asset\n")
            actual.write_bytes(b"asset\n")

            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--expected",
                            str(expected),
                            "--actual",
                            str(actual),
                            "--report",
                            str(report),
                        ]
                    ),
                    0,
                )
            self.assertEqual(json.loads(report.read_text())["status"], "VERIFIED")

            actual.write_bytes(b"changed\n")
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(["--expected", str(expected), "--actual", str(actual)]),
                    1,
                )

            with redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--expected",
                            str(expected),
                            "--actual",
                            str(root / "missing.zip"),
                        ]
                    ),
                    2,
                )


if __name__ == "__main__":
    unittest.main()
