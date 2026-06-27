import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.proofqa_transition_manifest import sha256_file
from scripts.proofqa_transition_manifest_builder import (
    TransitionManifestBuildError,
    build_transition_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/proofqa/transition-manifest-bundle"


class ProofQATransitionManifestBuilderTests(unittest.TestCase):
    def copy_source(self, destination: Path) -> Path:
        bundle = destination / "bundle"
        shutil.copytree(FIXTURE, bundle)
        (bundle / "manifest.json").unlink()
        return bundle

    def test_builder_recreates_committed_manifest_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_source(Path(directory))
            output = bundle / "manifest.json"
            result = build_transition_manifest(
                evidence_dir=bundle,
                output=output,
            )
            built = output.read_bytes()

        self.assertEqual(built, (FIXTURE / "manifest.json").read_bytes())
        self.assertEqual(result["status"], "MANIFEST_BUILT")
        self.assertEqual(result["files"], 5)
        self.assertEqual(result["verification_status"], "VERIFIED")
        self.assertEqual(
            result["manifest_sha256"],
            sha256_file(FIXTURE / "manifest.json"),
        )

    def test_repeated_build_is_deterministic_and_excludes_manifest_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_source(Path(directory))
            output = bundle / "manifest.json"
            build_transition_manifest(evidence_dir=bundle, output=output)
            first = output.read_bytes()
            build_transition_manifest(evidence_dir=bundle, output=output)
            second = output.read_bytes()
            payload = json.loads(second)

        self.assertEqual(first, second)
        self.assertNotIn("manifest.json", {entry["path"] for entry in payload["files"]})

    def test_output_must_be_inside_evidence_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.copy_source(root)
            with self.assertRaisesRegex(
                TransitionManifestBuildError,
                "must be inside",
            ):
                build_transition_manifest(
                    evidence_dir=bundle,
                    output=root / "outside.json",
                )

    def test_missing_referenced_evidence_fails_before_manifest_write(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_source(Path(directory))
            (bundle / "evidence/result.json").unlink()
            output = bundle / "manifest.json"
            with self.assertRaisesRegex(
                TransitionManifestBuildError,
                "references a missing source file",
            ):
                build_transition_manifest(evidence_dir=bundle, output=output)
            self.assertFalse(output.exists())

    def test_symlinked_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_source(Path(directory))
            target = bundle / "evidence/result.json"
            target.unlink()
            target.symlink_to(bundle / "evidence/action.json")
            with self.assertRaisesRegex(
                TransitionManifestBuildError,
                "contains a symlink",
            ):
                build_transition_manifest(
                    evidence_dir=bundle,
                    output=bundle / "manifest.json",
                )

    def test_duplicate_role_binding_fails_before_manifest_write(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_source(Path(directory))
            report_path = bundle / "transition-report.json"
            report = json.loads(report_path.read_text())
            report["evidence"]["result_ref"] = report["evidence"]["action_ref"]
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = bundle / "manifest.json"
            with self.assertRaisesRegex(
                TransitionManifestBuildError,
                "distinct file",
            ):
                build_transition_manifest(evidence_dir=bundle, output=output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
