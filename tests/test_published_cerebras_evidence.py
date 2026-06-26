import unittest
from pathlib import Path

from ibex_agent_verification.evidence import verify_manifest


class PublishedCerebrasEvidenceTests(unittest.TestCase):
    def test_v080_cerebras_bundle_matches_manifest(self):
        root = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "evidence"
            / "releases"
            / "v0.8.0"
            / "cerebras-live"
            / "bundle"
        )

        result = verify_manifest(
            evidence_dir=root,
            manifest_path=root / "manifest.json",
        )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["files_checked"], 3)
        self.assertEqual(result["mismatches"], [])


if __name__ == "__main__":
    unittest.main()
