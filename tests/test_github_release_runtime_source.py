import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.github_release_runtime_source import (
    GitHubReleaseRuntimeError,
    build_runtime_source,
    extract_live_release,
    observe_runtime_source,
)
from scripts.production_transition_source import validate_production_transition_source
from scripts.proofqa_transition_manifest_builder import build_transition_manifest
from tests.test_github_release_production_source import (
    ASSET_NAME,
    COMMIT,
    REPOSITORY,
    REPOSITORY_ID,
    TAG,
    build as build_production,
)


PROMOTION_WORKFLOW = ".github/workflows/ibex-evidence-promotion.yml"
RUNTIME_WORKFLOW = ".github/workflows/github-release-runtime-verification.yml"
RUNTIME_RUN_ID = 555555555
RUNTIME_RUN_ATTEMPT = 2
PACKAGE_VERSION = "0.8.1"
WHEEL_NAME = f"ibex_agent_verification-{PACKAGE_VERSION}-py3-none-any.whl"


def write_wheel(path: Path, *, entry_point="ibex_agent_verification.cli:main"):
    dist_info = f"ibex_agent_verification-{PACKAGE_VERSION}.dist-info"
    metadata = (
        "Metadata-Version: 2.1\n"
        "Name: ibex-agent-verification\n"
        f"Version: {PACKAGE_VERSION}\n"
        "Requires-Python: >=3.11\n\n"
    )
    entry_points = f"[console_scripts]\nibex-av = {entry_point}\n"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        wheel.writestr("ibex_agent_verification/__init__.py", "")
        wheel.writestr("ibex_agent_verification/cli.py", "def main(): return 0\n")
        wheel.writestr(f"{dist_info}/METADATA", metadata)
        wheel.writestr(f"{dist_info}/entry_points.txt", entry_points)
        wheel.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        wheel.writestr(f"{dist_info}/RECORD", "")


def install_report(wheel: Path, **overrides):
    report = {
        "schema_version": 1,
        "status": "INSTALLED",
        "package_name": "ibex-agent-verification",
        "package_version": PACKAGE_VERSION,
        "wheel_filename": wheel.name,
        "wheel_sha256": "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "python_version": "3.12.10",
        "python_executable": "/tmp/runtime-venv/bin/python",
        "sys_prefix": "/tmp/runtime-venv",
        "sys_base_prefix": "/opt/hostedtoolcache/Python/3.12.10/x64",
        "isolated": True,
        "module_file": (
            "/tmp/runtime-venv/lib/python3.12/site-packages/"
            "ibex_agent_verification/__init__.py"
        ),
    }
    report.update(overrides)
    return report


def cli_report(**overrides):
    report = {
        "status": "VERIFIED",
        "schema_version": 1,
        "files_checked": 6,
        "mismatches": [],
    }
    report.update(overrides)
    return report


def prepare(root: Path, *, wheel_entry="ibex_agent_verification.cli:main"):
    _, _, release = build_production(root)
    release_download = root / "release-download"
    source_dir = root / "runtime-live-source"
    extraction = extract_live_release(
        release=release,
        release_download_dir=release_download,
        output_dir=source_dir,
        expected_repository=REPOSITORY,
        expected_repository_id=REPOSITORY_ID,
        expected_commit=COMMIT,
        expected_release_tag=TAG,
        expected_asset_name=ASSET_NAME,
    )
    runtime_bundle = root / "runtime-bundle"
    runtime_bundle.mkdir()
    for path in source_dir.rglob("*"):
        relative = path.relative_to(source_dir)
        target = runtime_bundle / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    manifest_path = runtime_bundle / "manifest.json"
    build_transition_manifest(
        evidence_dir=runtime_bundle,
        output=manifest_path,
    )
    wheel = root / WHEEL_NAME
    write_wheel(wheel, entry_point=wheel_entry)
    return {
        "release": release,
        "release_download": release_download,
        "source_dir": source_dir,
        "runtime_bundle": runtime_bundle,
        "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
        "wheel": wheel,
        "extraction": extraction,
    }


def build_runtime(root: Path, **overrides):
    prepared = prepare(root, wheel_entry=overrides.pop("wheel_entry", "ibex_agent_verification.cli:main"))
    arguments = {
        "source_dir": prepared["source_dir"],
        "release": prepared["release"],
        "release_download_dir": prepared["release_download"],
        "runtime_bundle_dir": prepared["runtime_bundle"],
        "runtime_manifest": prepared["manifest"],
        "wheel_path": prepared["wheel"],
        "install_report": install_report(prepared["wheel"]),
        "cli_report": cli_report(),
        "output_dir": root / "runtime-source",
        "expected_repository": REPOSITORY,
        "expected_repository_id": REPOSITORY_ID,
        "expected_commit": COMMIT,
        "expected_promotion_workflow": PROMOTION_WORKFLOW,
        "expected_release_tag": TAG,
        "expected_asset_name": ASSET_NAME,
        "expected_package_version": PACKAGE_VERSION,
        "runtime_workflow": RUNTIME_WORKFLOW,
        "runtime_run_id": RUNTIME_RUN_ID,
        "runtime_run_attempt": RUNTIME_RUN_ATTEMPT,
    }
    arguments.update(overrides)
    result = build_runtime_source(**arguments)
    return result, arguments["output_dir"], prepared


class GitHubReleaseRuntimeSourceTests(unittest.TestCase):
    def test_clean_runtime_builds_valid_transition_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, source, _ = build_runtime(root)
            destination_id = result["runtime_source"]["destination"]["identity"]

            validation = validate_production_transition_source(
                source_dir=source,
                expected_repository=REPOSITORY,
                expected_commit=COMMIT,
                expected_workflow=RUNTIME_WORKFLOW,
                expected_run_id=RUNTIME_RUN_ID,
                expected_run_attempt=RUNTIME_RUN_ATTEMPT,
                expected_event="workflow_run",
                expected_branch="main",
                expected_environment="ibex-runtime-verification",
                expected_destination_id=destination_id,
            )

            self.assertEqual(result["status"], "EXECUTED")
            self.assertEqual(validation["status"], "VALIDATED")
            self.assertEqual(result["runtime"]["cli"]["status"], "VERIFIED")
            self.assertEqual(result["runtime"]["manifest"]["files_checked"], 6)
            self.assertIn("workflow-run:555555555", destination_id)
            self.assertIn(
                "not a physical production execution claim",
                result["runtime_source"]["claim_boundary"],
            )

    def test_wrong_wheel_entry_point_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                GitHubReleaseRuntimeError, "wheel ibex-av entry point mismatch"
            ):
                build_runtime(Path(directory), wheel_entry="foreign.module:main")

    def test_install_report_wheel_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare(root)
            report = install_report(
                prepared["wheel"], wheel_sha256="sha256:" + "0" * 64
            )
            with self.assertRaisesRegex(
                GitHubReleaseRuntimeError, "installed wheel digest mismatch"
            ):
                build_runtime_source(
                    source_dir=prepared["source_dir"],
                    release=prepared["release"],
                    release_download_dir=prepared["release_download"],
                    runtime_bundle_dir=prepared["runtime_bundle"],
                    runtime_manifest=prepared["manifest"],
                    wheel_path=prepared["wheel"],
                    install_report=report,
                    cli_report=cli_report(),
                    output_dir=root / "runtime-source",
                    expected_repository=REPOSITORY,
                    expected_repository_id=REPOSITORY_ID,
                    expected_commit=COMMIT,
                    expected_promotion_workflow=PROMOTION_WORKFLOW,
                    expected_release_tag=TAG,
                    expected_asset_name=ASSET_NAME,
                    expected_package_version=PACKAGE_VERSION,
                    runtime_workflow=RUNTIME_WORKFLOW,
                    runtime_run_id=RUNTIME_RUN_ID,
                    runtime_run_attempt=RUNTIME_RUN_ATTEMPT,
                )

    def test_non_virtual_environment_install_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare(root)
            report = install_report(
                prepared["wheel"],
                sys_base_prefix="/tmp/runtime-venv",
            )
            with self.assertRaisesRegex(
                GitHubReleaseRuntimeError, "not executed inside a virtual environment"
            ):
                build_runtime_source(
                    source_dir=prepared["source_dir"],
                    release=prepared["release"],
                    release_download_dir=prepared["release_download"],
                    runtime_bundle_dir=prepared["runtime_bundle"],
                    runtime_manifest=prepared["manifest"],
                    wheel_path=prepared["wheel"],
                    install_report=report,
                    cli_report=cli_report(),
                    output_dir=root / "runtime-source",
                    expected_repository=REPOSITORY,
                    expected_repository_id=REPOSITORY_ID,
                    expected_commit=COMMIT,
                    expected_promotion_workflow=PROMOTION_WORKFLOW,
                    expected_release_tag=TAG,
                    expected_asset_name=ASSET_NAME,
                    expected_package_version=PACKAGE_VERSION,
                    runtime_workflow=RUNTIME_WORKFLOW,
                    runtime_run_id=RUNTIME_RUN_ID,
                    runtime_run_attempt=RUNTIME_RUN_ATTEMPT,
                )

    def test_cli_integrity_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare(root)
            with self.assertRaisesRegex(
                GitHubReleaseRuntimeError, "must be schema v1 VERIFIED"
            ):
                build_runtime_source(
                    source_dir=prepared["source_dir"],
                    release=prepared["release"],
                    release_download_dir=prepared["release_download"],
                    runtime_bundle_dir=prepared["runtime_bundle"],
                    runtime_manifest=prepared["manifest"],
                    wheel_path=prepared["wheel"],
                    install_report=install_report(prepared["wheel"]),
                    cli_report=cli_report(status="INTEGRITY_MISMATCH"),
                    output_dir=root / "runtime-source",
                    expected_repository=REPOSITORY,
                    expected_repository_id=REPOSITORY_ID,
                    expected_commit=COMMIT,
                    expected_promotion_workflow=PROMOTION_WORKFLOW,
                    expected_release_tag=TAG,
                    expected_asset_name=ASSET_NAME,
                    expected_package_version=PACKAGE_VERSION,
                    runtime_workflow=RUNTIME_WORKFLOW,
                    runtime_run_id=RUNTIME_RUN_ID,
                    runtime_run_attempt=RUNTIME_RUN_ATTEMPT,
                )

    def test_unlisted_runtime_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare(root)
            (prepared["runtime_bundle"] / "extra.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(
                GitHubReleaseRuntimeError,
                "missing or additional non-manifest files",
            ):
                build_runtime_source(
                    source_dir=prepared["source_dir"],
                    release=prepared["release"],
                    release_download_dir=prepared["release_download"],
                    runtime_bundle_dir=prepared["runtime_bundle"],
                    runtime_manifest=prepared["manifest"],
                    wheel_path=prepared["wheel"],
                    install_report=install_report(prepared["wheel"]),
                    cli_report=cli_report(),
                    output_dir=root / "runtime-source",
                    expected_repository=REPOSITORY,
                    expected_repository_id=REPOSITORY_ID,
                    expected_commit=COMMIT,
                    expected_promotion_workflow=PROMOTION_WORKFLOW,
                    expected_release_tag=TAG,
                    expected_asset_name=ASSET_NAME,
                    expected_package_version=PACKAGE_VERSION,
                    runtime_workflow=RUNTIME_WORKFLOW,
                    runtime_run_id=RUNTIME_RUN_ID,
                    runtime_run_attempt=RUNTIME_RUN_ATTEMPT,
                )

    def test_signer_observation_binds_runtime_identity_and_release_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, source, prepared = build_runtime(root)
            provenance = json.loads(
                (source / "source-provenance.json").read_text(encoding="utf-8")
            )

            observation = observe_runtime_source(
                provenance=provenance,
                release=prepared["release"],
                expected_repository=REPOSITORY,
                expected_repository_id=REPOSITORY_ID,
                expected_commit=COMMIT,
                expected_runtime_workflow=RUNTIME_WORKFLOW,
                expected_runtime_run_id=RUNTIME_RUN_ID,
                expected_runtime_run_attempt=RUNTIME_RUN_ATTEMPT,
                expected_release_tag=TAG,
                expected_asset_name=ASSET_NAME,
            )

            self.assertEqual(observation["status"], "OBSERVED")
            self.assertEqual(
                observation["destination_id"],
                result["runtime_source"]["destination"]["identity"],
            )

    def test_signer_observation_rejects_foreign_runtime_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, source, prepared = build_runtime(root)
            provenance = json.loads(
                (source / "source-provenance.json").read_text(encoding="utf-8")
            )

            with self.assertRaisesRegex(
                GitHubReleaseRuntimeError, "runtime deployment run_id mismatch"
            ):
                observe_runtime_source(
                    provenance=provenance,
                    release=prepared["release"],
                    expected_repository=REPOSITORY,
                    expected_repository_id=REPOSITORY_ID,
                    expected_commit=COMMIT,
                    expected_runtime_workflow=RUNTIME_WORKFLOW,
                    expected_runtime_run_id=999999999,
                    expected_runtime_run_attempt=RUNTIME_RUN_ATTEMPT,
                    expected_release_tag=TAG,
                    expected_asset_name=ASSET_NAME,
                )


if __name__ == "__main__":
    unittest.main()
