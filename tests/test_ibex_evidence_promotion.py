import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.ibex_evidence_promotion import (
    IbexEvidencePromotionError,
    promote_ibex_evidence,
)
from scripts.production_transition_source import validate_production_transition_source
from scripts.trusted_transition_artifact import TrustedTransitionArtifactError


REPOSITORY = "safal207/ibex-agent-verification"
COMMIT = "a" * 40
IBEX_REF = "022f084096baed0a9b5ebdf697ed2965f13e8ed8"
E2E_WORKFLOW = ".github/workflows/ibex-e2e.yml"
PROMOTION_WORKFLOW = ".github/workflows/ibex-evidence-promotion.yml"
E2E_RUN_ID = 111111111
E2E_RUN_ATTEMPT = 2
PROMOTION_RUN_ID = 222222222
PROMOTION_RUN_ATTEMPT = 1
DESTINATION_ENVIRONMENT = "ibex-evidence-release"
DESTINATION_ID = (
    "github-actions:repository-id:1278529886:environment:ibex-evidence-release"
)


def canonical_json(payload):
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def base_files():
    trace = b"trace instruction 1\ntrace instruction 2\n"
    parser = {
        "status": "PARSED",
        "instructions": 2,
        "source_sha256": hashlib.sha256(trace).hexdigest(),
    }
    causal = {
        "status": "ENRICHED",
        "alignment_ratio": 1.0,
        "retirement_times": 2,
        "matched_retirement_times": 2,
        "timing_samples": 1,
        "missing_optional_signals": [],
    }
    return {
        "commands.sh": b"set -euo pipefail\necho ibex\n",
        "logs/empty.stderr": b"",
        "normalized/architectural.jsonl": b'{"step":1}\n',
        "normalized/causal-report.json": canonical_json(causal),
        "normalized/metadata.jsonl": b'{"step":1,"meta":true}\n',
        "normalized/parser-report.json": canonical_json(parser),
        "normalized/timing-causal.jsonl": b'{"step":1,"cause":"MEMORY_WAIT"}\n',
        "normalized/timing-report.json": canonical_json(
            {"anomalies": 1, "status": "ANALYZED"}
        ),
        "normalized/timing.jsonl": b'{"step":1,"cycles":2}\n',
        "raw/hello_test.elf": b"ELF fixture bytes",
        "raw/ibex_simple_system.log": (
            b"Hello simple system\nDEADBEEF\nBAADF00D\nTick!\nTock!\n"
        ),
        "raw/sim.fst": b"FST fixture bytes",
        "raw/simulator.stdout": (
            b"Simulation of Ibex\n"
            b"Terminating simulation by software request.\n"
            b"Received $finish() from Verilog\n"
        ),
        "raw/trace_core_00000000.log": trace,
        "timing-exit-code.txt": b"1\n",
        "tool-versions.txt": b"python=Python 3.12\nverilator=Verilator 5.020\n",
    }


def manifest_for(files, *, commit=COMMIT, ibex_ref=IBEX_REF, simulation_exit=0):
    return {
        "schema_version": 1,
        "generated_at_utc": "2026-06-28T00:00:00+00:00",
        "project": {"repository": REPOSITORY, "commit": commit},
        "dut": {
            "configuration": "small",
            "program": "examples/sw/simple_system/hello_test/hello_test.elf",
            "repository": "lowRISC/ibex",
            "requested_ref": ibex_ref,
            "resolved_commit": ibex_ref,
            "simulator": "verilator",
        },
        "result": {
            "simulation_exit_code": simulation_exit,
            "timing_analyzer_exit_code": 1,
            "timing_anomaly_detected": True,
            "trace_parse_status": "PARSED",
        },
        "tool_versions": {
            "python": "Python 3.12",
            "verilator": "Verilator 5.020",
        },
        "commands_file": "commands.sh",
        "files": [
            {
                "path": path,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in sorted(files.items())
        ],
    }


def write_archive(
    archive: Path,
    *,
    files=None,
    manifest=None,
    extra_files=None,
    symlink_path=None,
):
    payloads = dict(base_files() if files is None else files)
    manifest_payload = manifest or manifest_for(payloads)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path, content in sorted(payloads.items()):
            zipped.writestr(path, content)
        for path, content in sorted((extra_files or {}).items()):
            zipped.writestr(path, content)
        if symlink_path is not None:
            info = zipfile.ZipInfo(symlink_path)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zipped.writestr(info, "target")
        zipped.writestr("manifest.json", canonical_json(manifest_payload))


def selection_for(archive: Path, *, commit=COMMIT):
    archive_bytes = archive.read_bytes()
    return {
        "schema_version": 1,
        "kind": "trusted-transition-artifact-selection",
        "status": "SELECTED",
        "repository": REPOSITORY,
        "repository_id": 1278529886,
        "head_repository_id": 1278529886,
        "run_id": E2E_RUN_ID,
        "run_attempt": E2E_RUN_ATTEMPT,
        "workflow": E2E_WORKFLOW,
        "head_branch": "main",
        "head_sha": commit,
        "artifact": {
            "id": 333333333,
            "name": f"ibex-verilator-evidence-{commit}",
            "size_bytes": len(archive_bytes),
            "digest": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
            "url": (
                "https://api.github.com/repos/"
                f"{REPOSITORY}/actions/artifacts/333333333"
            ),
            "archive_download_url": (
                "https://api.github.com/repos/"
                f"{REPOSITORY}/actions/artifacts/333333333/zip"
            ),
        },
    }


def promote(root: Path, *, archive_builder=None, selection_mutator=None):
    download = root / "download"
    download.mkdir(parents=True)
    archive = download / "artifact.zip"
    if archive_builder is None:
        write_archive(archive)
    else:
        archive_builder(archive)
    selection = selection_for(archive)
    if selection_mutator is not None:
        selection_mutator(selection)
    result = promote_ibex_evidence(
        download_dir=download,
        selection=selection,
        extracted_dir=root / "extracted",
        output_dir=root / "source",
        repository_name=REPOSITORY,
        source_commit=COMMIT,
        expected_e2e_workflow=E2E_WORKFLOW,
        expected_e2e_run_id=E2E_RUN_ID,
        expected_e2e_run_attempt=E2E_RUN_ATTEMPT,
        expected_ibex_ref=IBEX_REF,
        promotion_workflow=PROMOTION_WORKFLOW,
        promotion_run_id=PROMOTION_RUN_ID,
        promotion_run_attempt=PROMOTION_RUN_ATTEMPT,
        promotion_event="workflow_run",
        branch="main",
        destination_environment=DESTINATION_ENVIRONMENT,
        destination_id=DESTINATION_ID,
    )
    return result, root / "source"


class IbexEvidencePromotionTests(unittest.TestCase):
    def test_exact_e2e_artifact_builds_valid_transition_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, source = promote(root)

            validation = validate_production_transition_source(
                source_dir=source,
                expected_repository=REPOSITORY,
                expected_commit=COMMIT,
                expected_workflow=PROMOTION_WORKFLOW,
                expected_run_id=PROMOTION_RUN_ID,
                expected_run_attempt=PROMOTION_RUN_ATTEMPT,
                expected_event="workflow_run",
                expected_branch="main",
                expected_environment=DESTINATION_ENVIRONMENT,
                expected_destination_id=DESTINATION_ID,
            )

            self.assertEqual(result["status"], "PROMOTED")
            self.assertEqual(validation["status"], "VALIDATED")
            self.assertEqual(result["upstream"]["files_verified"], 16)
            self.assertEqual(result["observation"]["simulation_exit_code"], 0)
            self.assertEqual(result["observation"]["trace_parse_status"], "PARSED")
            self.assertEqual(
                result["release"]["subject_digest"],
                result["upstream"]["artifact"]["digest"],
            )
            self.assertIn(
                "not a production deployment claim",
                result["claim_boundary"],
            )
            self.assertEqual(len(result["source_files"]), 6)

    def test_zero_byte_manifest_member_is_accepted_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = promote(Path(directory))
            self.assertEqual(result["upstream"]["files_verified"], 16)

    def test_archive_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def mutate(selection):
                selection["artifact"]["digest"] = "sha256:" + "0" * 64

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "downloaded archive digest mismatch",
            ):
                promote(root, selection_mutator=mutate)

    def test_unlisted_archive_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def build(archive):
                write_archive(
                    archive,
                    extra_files={"raw/unlisted.bin": b"untrusted"},
                )

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "archive and manifest inventory differ",
            ):
                promote(root, archive_builder=build)

    def test_one_byte_manifest_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def build(archive):
                files = base_files()
                manifest = manifest_for(files)
                files["raw/trace_core_00000000.log"] += b"x"
                write_archive(archive, files=files, manifest=manifest)

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "size for raw/trace_core_00000000.log mismatch",
            ):
                promote(root, archive_builder=build)

    def test_wrong_project_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def build(archive):
                files = base_files()
                write_archive(
                    archive,
                    files=files,
                    manifest=manifest_for(files, commit="b" * 40),
                )

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "project commit mismatch",
            ):
                promote(root, archive_builder=build)

    def test_wrong_pinned_ibex_ref_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def build(archive):
                files = base_files()
                write_archive(
                    archive,
                    files=files,
                    manifest=manifest_for(files, ibex_ref="c" * 40),
                )

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "DUT requested_ref mismatch",
            ):
                promote(root, archive_builder=build)

    def test_failed_simulation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def build(archive):
                files = base_files()
                write_archive(
                    archive,
                    files=files,
                    manifest=manifest_for(files, simulation_exit=1),
                )

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "simulation exit code mismatch",
            ):
                promote(root, archive_builder=build)

    def test_missing_runtime_marker_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def build(archive):
                files = base_files()
                files["raw/ibex_simple_system.log"] = b"Hello simple system\n"
                write_archive(
                    archive,
                    files=files,
                    manifest=manifest_for(files),
                )

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "lacks expected marker",
            ):
                promote(root, archive_builder=build)

    def test_symbolic_link_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def build(archive):
                write_archive(archive, symlink_path="raw/link")

            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "symbolic link",
            ):
                promote(root, archive_builder=build)

    def test_foreign_workflow_selection_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def mutate(selection):
                selection["workflow"] = ".github/workflows/foreign.yml"

            with self.assertRaisesRegex(
                IbexEvidencePromotionError,
                "selection workflow mismatch",
            ):
                promote(root, selection_mutator=mutate)


if __name__ == "__main__":
    unittest.main()
