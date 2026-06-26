import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ibex_agent_verification.cli import main
from ibex_agent_verification.evidence import (
    EvidenceError,
    build_manifest,
    collect_files,
    parse_key_value_file,
    verify_manifest,
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


class EvidenceVerificationTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> Path:
        (root / "logs").mkdir()
        (root / "commands.sh").write_text("echo replay\n", encoding="utf-8")
        (root / "logs" / "simulator.stdout").write_text("PASS\n", encoding="utf-8")
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "files": collect_files(root, manifest_path),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def test_verifies_exact_manifest_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_bundle(root)
            result = verify_manifest(evidence_dir=root, manifest_path=manifest)

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["files_checked"], 2)
        self.assertEqual(result["mismatches"], [])

    def test_reports_changed_file_without_hiding_other_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_bundle(root)
            (root / "commands.sh").write_text("echo changed\n", encoding="utf-8")
            result = verify_manifest(evidence_dir=root, manifest_path=manifest)

        self.assertEqual(result["status"], "INTEGRITY_MISMATCH")
        problems = {item["problem"] for item in result["mismatches"]}
        self.assertIn("SIZE_MISMATCH", problems)
        self.assertIn("SHA256_MISMATCH", problems)

    def test_reports_unlisted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_bundle(root)
            (root / "late.log").write_text("not in manifest\n", encoding="utf-8")
            result = verify_manifest(evidence_dir=root, manifest_path=manifest)

        self.assertEqual(result["status"], "INTEGRITY_MISMATCH")
        self.assertIn(
            {"path": "late.log", "problem": "UNLISTED"}, result["mismatches"]
        )

    def test_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "files": [
                            {
                                "path": "../outside",
                                "size_bytes": 0,
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "canonical and relative"):
                verify_manifest(evidence_dir=root, manifest_path=manifest)

    def test_rejects_duplicate_manifest_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_bundle(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["files"].append(dict(payload["files"][0]))
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "duplicate path"):
                verify_manifest(evidence_dir=root, manifest_path=manifest)

    def test_cli_exit_codes_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_bundle(root)
            report = root / "verification.json"
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "verify-evidence",
                            "--manifest",
                            str(manifest),
                            "--report",
                            str(report),
                        ]
                    ),
                    0,
                )
            self.assertEqual(json.loads(report.read_text())["status"], "VERIFIED")

            (root / "commands.sh").write_text("tampered\n", encoding="utf-8")
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(["verify-evidence", "--manifest", str(manifest)]), 1
                )

            manifest.write_text("{}\n", encoding="utf-8")
            with redirect_stderr(StringIO()):
                self.assertEqual(
                    main(["verify-evidence", "--manifest", str(manifest)]), 2
                )


if __name__ == "__main__":
    unittest.main()
