import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.evidence import (
    EvidenceError,
    build_manifest,
    parse_key_value_file,
    write_manifest,
)


class EvidenceManifestTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> tuple[Path, Path, Path]:
        evidence = root / "evidence"
        (evidence / "raw").mkdir(parents=True)
        (evidence / "normalized").mkdir()
        (evidence / "raw" / "trace.log").write_text("trace\n", encoding="utf-8")
        (evidence / "normalized" / "trace.jsonl").write_text(
            '{"step":0}\n', encoding="utf-8"
        )
        versions = evidence / "tool-versions.txt"
        versions.write_text("python=3.12\nverilator=5.020\n", encoding="utf-8")
        commands = evidence / "commands.sh"
        commands.write_text("fusesoc --version\n", encoding="utf-8")
        return evidence, versions, commands

    def test_manifest_hashes_files_and_sorts_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence, versions, commands = self.make_bundle(root)
            output = evidence / "manifest.json"
            manifest = write_manifest(
                evidence_dir=evidence,
                output=output,
                project_sha="project123",
                ibex_requested_ref="requested456",
                ibex_resolved_sha="resolved789",
                ibex_config="small",
                timing_exit_code=1,
                tool_versions_file=versions,
                commands_file=commands,
            )
            saved = json.loads(output.read_text(encoding="utf-8"))

        paths = [item["path"] for item in manifest["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertNotIn("manifest.json", paths)
        self.assertEqual(saved["result"]["timing_anomaly_detected"], True)
        trace = next(item for item in saved["files"] if item["path"] == "raw/trace.log")
        self.assertEqual(
            trace["sha256"], hashlib.sha256(b"trace\n").hexdigest()
        )

    def test_tool_versions_require_unique_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "versions.txt"
            path.write_text("python=3.12\npython=3.13\n", encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "duplicate key"):
                parse_key_value_file(path)

    def test_invalid_timing_exit_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence, versions, commands = self.make_bundle(root)
            with self.assertRaisesRegex(EvidenceError, "must be 0 or 1"):
                build_manifest(
                    evidence_dir=evidence,
                    output=evidence / "manifest.json",
                    project_sha="p",
                    ibex_requested_ref="r",
                    ibex_resolved_sha="s",
                    ibex_config="small",
                    timing_exit_code=2,
                    tool_versions_file=versions,
                    commands_file=commands,
                )


if __name__ == "__main__":
    unittest.main()
