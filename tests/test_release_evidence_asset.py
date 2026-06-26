import tempfile
import unittest
from pathlib import Path

from scripts.build_release_evidence_asset import build_asset


class ReleaseEvidenceAssetTests(unittest.TestCase):
    def test_asset_is_deterministic(self):
        source = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "releases" / "v0.8.0" / "cerebras-live"
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            first_digest = build_asset(source, first)
            second_digest = build_asset(source, second)
            self.assertEqual(first_digest, second_digest)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
