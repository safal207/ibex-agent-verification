#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import re
import sys
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.github_release_production_source import (
        GitHubReleaseProductionError,
        observe_release,
    )
    from scripts.production_transition_source import (
        ProductionTransitionSourceError,
        validate_production_transition_source,
    )
    from scripts.trusted_transition_artifact import (
        EXPECTED_SOURCE_FILES,
        TrustedTransitionArtifactError,
        extract_artifact,
        load_json_object,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
        write_json,
    )
except ImportError:
    from github_release_production_source import (
        GitHubReleaseProductionError,
        observe_release,
    )
    from production_transition_source import (
        ProductionTransitionSourceError,
        validate_production_transition_source,
    )
    from trusted_transition_artifact import (
        EXPECTED_SOURCE_FILES,
        TrustedTransitionArtifactError,
        extract_artifact,
        load_json_object,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
        write_json,
    )


class GitHubReleaseRuntimeError(ValueError):
    """Raised when released bytes were not executed under the required contract."""


_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9.+-]*)?$")
_PACKAGE_NAME = "ibex-agent-verification"
_ENTRY_POINT = "ibex-av = ibex_agent_verification.cli:main"
_RUNTIME_ENVIRONMENT = "ibex-runtime-verification"
_PROMOTION_ENVIRONMENT = "ibex-evidence-release"
_CLAIM_BOUNDARY = (
    "This verified transition proves that a wheel built from the exact main-branch "
    "commit was installed without network dependency resolution into a fresh isolated "
    "Python virtual environment on a GitHub-hosted Ubuntu runner, and that the installed "
    "ibex-av executable successfully verified the exact customer-release bytes downloaded "
    "from the live GitHub Release service. It does not prove installation or execution on "
    "a customer-controlled host, long-lived service health, physical hardware behavior, "
    "or independent human approval, and it is not a physical production execution claim."
)


def _require_equal(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise GitHubReleaseRuntimeError(
            f"{label} mismatch: expected {expected!r}, got {actual!r}"
        )


def _exact_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise GitHubReleaseRuntimeError(
            f"{label} keys mismatch; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _version(value: Any, *, label: str) -> str:
    normalized = text(value, label=label, maximum=100)
    if _VERSION_RE.fullmatch(normalized) is None:
        raise GitHubReleaseRuntimeError(f"{label} is not a canonical package version")
    return normalized


def _single_file(directory: Path, *, label: str) -> Path:
    if directory.is_symlink():
        raise GitHubReleaseRuntimeError(f"{label} must not be a symlink")
    root = directory.resolve(strict=True)
    if not root.is_dir():
        raise GitHubReleaseRuntimeError(f"{label} must be a directory")
    entries = list(root.iterdir())
    if len(entries) != 1:
        raise GitHubReleaseRuntimeError(
            f"{label} must contain exactly one file, found {len(entries)}"
        )
    candidate = entries[0]
    if candidate.is_symlink() or not candidate.is_file():
        raise GitHubReleaseRuntimeError(f"{label} entry must be a regular file")
    return candidate


def _runtime_identity(repository_id: int, run_id: int, run_attempt: int) -> str:
    return (
        f"github-actions:repository-id:{repository_id}:"
        f"environment:{_RUNTIME_ENVIRONMENT}:workflow-run:{run_id}:"
        f"attempt:{run_attempt}:runner:github-hosted-ubuntu-24.04"
    )


def _promotion_identity(repository_id: int) -> str:
    return (
        f"github-actions:repository-id:{repository_id}:"
        f"environment:{_PROMOTION_ENVIRONMENT}"
    )


def inspect_wheel(
    wheel_path: Path,
    *,
    expected_package_name: str,
    expected_version: str,
) -> dict[str, Any]:
    if wheel_path.is_symlink() or not wheel_path.is_file():
        raise GitHubReleaseRuntimeError("wheel must be a regular non-symlink file")
    if wheel_path.suffix != ".whl":
        raise GitHubReleaseRuntimeError("runtime package must be a wheel")
    size_bytes = wheel_path.stat().st_size
    if size_bytes <= 0 or size_bytes > 10 * 1024 * 1024:
        raise GitHubReleaseRuntimeError("wheel size is outside the accepted limit")
    package_name = text(expected_package_name, label="expected package name", maximum=200)
    package_version = _version(expected_version, label="expected package version")
    try:
        with zipfile.ZipFile(wheel_path, "r") as archive:
            names = archive.namelist()
            if not names or len(names) > 500:
                raise GitHubReleaseRuntimeError("wheel entry count is unsafe")
            if any(
                name.startswith("/")
                or "\\" in name
                or any(part in {"", ".", ".."} for part in PurePosixPath(name).parts)
                for name in names
            ):
                raise GitHubReleaseRuntimeError("wheel contains a noncanonical path")
            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            entry_point_names = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if len(metadata_names) != 1 or len(entry_point_names) != 1:
                raise GitHubReleaseRuntimeError(
                    "wheel must contain exactly one METADATA and entry_points.txt"
                )
            metadata = Parser().parsestr(
                archive.read(metadata_names[0]).decode("utf-8")
            )
            _require_equal(metadata.get("Name"), package_name, label="wheel package name")
            _require_equal(
                metadata.get("Version"), package_version, label="wheel package version"
            )
            requires_python = metadata.get("Requires-Python")
            if not isinstance(requires_python, str) or not requires_python.startswith(">=3.11"):
                raise GitHubReleaseRuntimeError(
                    "wheel Requires-Python must preserve the >=3.11 contract"
                )
            entry_points = configparser.ConfigParser()
            entry_points.read_string(
                archive.read(entry_point_names[0]).decode("utf-8")
            )
            actual_entry = entry_points.get(
                "console_scripts", "ibex-av", fallback=None
            )
            _require_equal(
                f"ibex-av = {actual_entry}" if actual_entry else None,
                _ENTRY_POINT,
                label="wheel ibex-av entry point",
            )
            if "ibex_agent_verification/cli.py" not in names:
                raise GitHubReleaseRuntimeError("wheel lacks ibex_agent_verification/cli.py")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as error:
        raise GitHubReleaseRuntimeError(f"unable to inspect wheel: {error}") from error
    return {
        "filename": wheel_path.name,
        "size_bytes": size_bytes,
        "sha256": f"sha256:{sha256_file(wheel_path)}",
        "package_name": package_name,
        "package_version": package_version,
        "requires_python": requires_python,
        "entry_point": _ENTRY_POINT,
    }


def validate_install_report(
    report: dict[str, Any],
    *,
    expected_package_name: str,
    expected_version: str,
    expected_wheel: dict[str, Any],
) -> dict[str, Any]:
    _exact_keys(
        report,
        {
            "schema_version",
            "status",
            "package_name",
            "package_version",
            "wheel_filename",
            "wheel_sha256",
            "python_version",
            "python_executable",
            "sys_prefix",
            "sys_base_prefix",
            "isolated",
            "module_file",
        },
        label="runtime install report",
    )
    if report.get("schema_version") != 1 or report.get("status") != "INSTALLED":
        raise GitHubReleaseRuntimeError(
            "runtime install report must be schema v1 INSTALLED"
        )
    _require_equal(
        report.get("package_name"), expected_package_name, label="installed package name"
    )
    _require_equal(
        report.get("package_version"), expected_version, label="installed package version"
    )
    _require_equal(
        report.get("wheel_filename"),
        expected_wheel["filename"],
        label="installed wheel filename",
    )
    _require_equal(
        report.get("wheel_sha256"),
        expected_wheel["sha256"],
        label="installed wheel digest",
    )
    python_version = text(
        report.get("python_version"), label="runtime Python version", maximum=200
    )
    if not python_version.startswith(("3.11.", "3.12.", "3.13.")):
        raise GitHubReleaseRuntimeError("runtime Python version is outside the supported set")
    python_executable = text(
        report.get("python_executable"), label="runtime Python executable", maximum=1000
    )
    sys_prefix = text(report.get("sys_prefix"), label="runtime sys.prefix", maximum=1000)
    sys_base_prefix = text(
        report.get("sys_base_prefix"), label="runtime sys.base_prefix", maximum=1000
    )
    if sys_prefix == sys_base_prefix:
        raise GitHubReleaseRuntimeError("package was not executed inside a virtual environment")
    if not python_executable.startswith(sys_prefix.rstrip("/") + "/"):
        raise GitHubReleaseRuntimeError(
            "runtime Python executable is not inside the virtual environment"
        )
    if report.get("isolated") is not True:
        raise GitHubReleaseRuntimeError("runtime import check was not executed with -I")
    module_file = text(
        report.get("module_file"), label="installed module file", maximum=2000
    )
    if not module_file.startswith(sys_prefix.rstrip("/") + "/") or not module_file.endswith(
        "/ibex_agent_verification/__init__.py"
    ):
        raise GitHubReleaseRuntimeError(
            "installed module did not load from the isolated virtual environment"
        )
    return {
        "status": "INSTALLED",
        "package_name": expected_package_name,
        "package_version": expected_version,
        "python_version": python_version,
        "python_executable": python_executable,
        "sys_prefix": sys_prefix,
        "module_file": module_file,
    }


def validate_cli_report(report: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        report,
        {"status", "schema_version", "files_checked", "mismatches"},
        label="installed CLI report",
    )
    if report.get("schema_version") != 1 or report.get("status") != "VERIFIED":
        raise GitHubReleaseRuntimeError(
            "installed ibex-av report must be schema v1 VERIFIED"
        )
    if report.get("files_checked") != len(EXPECTED_SOURCE_FILES):
        raise GitHubReleaseRuntimeError("installed ibex-av verified an unexpected file count")
    if report.get("mismatches") != []:
        raise GitHubReleaseRuntimeError("installed ibex-av reported integrity mismatches")
    return {
        "status": "VERIFIED",
        "files_checked": report["files_checked"],
        "mismatches": [],
    }


def validate_runtime_manifest(
    manifest: dict[str, Any],
    *,
    runtime_bundle_dir: Path,
) -> dict[str, Any]:
    _exact_keys(manifest, {"schema_version", "files"}, label="runtime manifest")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise GitHubReleaseRuntimeError("runtime manifest must be schema v1 with files")
    files = manifest["files"]
    if len(files) != len(EXPECTED_SOURCE_FILES):
        raise GitHubReleaseRuntimeError("runtime manifest file count mismatch")
    root = runtime_bundle_dir.resolve(strict=True)
    inventory: dict[str, dict[str, Any]] = {}
    folded: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise GitHubReleaseRuntimeError(
                f"runtime manifest files[{index}] must be an object"
            )
        _exact_keys(
            item,
            {"path", "size_bytes", "sha256"},
            label=f"runtime manifest files[{index}]",
        )
        path = text(item.get("path"), label=f"runtime manifest files[{index}].path")
        pure = PurePosixPath(path)
        if pure.as_posix() != path or any(part in {"", ".", ".."} for part in pure.parts):
            raise GitHubReleaseRuntimeError(f"runtime manifest path is unsafe: {path}")
        key = path.casefold()
        if path in inventory or key in folded:
            raise GitHubReleaseRuntimeError(
                f"runtime manifest duplicates or case-collides path: {path}"
            )
        folded.add(key)
        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise GitHubReleaseRuntimeError(f"runtime manifest size is invalid: {path}")
        raw_sha = item.get("sha256")
        if not isinstance(raw_sha, str) or re.fullmatch(r"[0-9a-f]{64}", raw_sha) is None:
            raise GitHubReleaseRuntimeError(f"runtime manifest digest is invalid: {path}")
        candidate = root.joinpath(*pure.parts)
        if candidate.is_symlink() or not candidate.is_file():
            raise GitHubReleaseRuntimeError(f"runtime manifest path is not regular: {path}")
        _require_equal(candidate.stat().st_size, size_bytes, label=f"runtime file size {path}")
        _require_equal(sha256_file(candidate), raw_sha, label=f"runtime file digest {path}")
        inventory[path] = {
            "path": path,
            "size_bytes": size_bytes,
            "sha256": raw_sha,
        }
    if set(inventory) != EXPECTED_SOURCE_FILES:
        raise GitHubReleaseRuntimeError(
            "runtime manifest is not the exact six-file production source set"
        )
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != (root / "manifest.json").resolve()
    }
    if actual_files != EXPECTED_SOURCE_FILES:
        raise GitHubReleaseRuntimeError(
            "runtime bundle contains missing or additional non-manifest files"
        )
    return {
        "status": "VERIFIED",
        "files_checked": len(inventory),
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "files": [inventory[path] for path in sorted(inventory)],
    }


def extract_live_release(
    *,
    release: dict[str, Any],
    release_download_dir: Path,
    output_dir: Path,
    expected_repository: str,
    expected_repository_id: int,
    expected_commit: str,
    expected_release_tag: str,
    expected_asset_name: str,
) -> dict[str, Any]:
    downloaded_asset = _single_file(
        release_download_dir, label="live release download directory"
    )
    observation = observe_release(
        release=release,
        expected_repository=expected_repository,
        expected_repository_id=expected_repository_id,
        expected_commit=expected_commit,
        expected_tag=expected_release_tag,
        expected_asset_name=expected_asset_name,
        downloaded_asset=downloaded_asset,
    )
    live_digest = observation["asset"]["downloaded_digest"]
    if live_digest is None:
        raise GitHubReleaseRuntimeError("live release download lacks a SHA-256 digest")
    synthetic_selection = {
        "schema_version": 1,
        "status": "SELECTED",
        "repository": observation["repository"],
        "head_sha": observation["source_commit"],
        "artifact": {
            "id": observation["asset"]["id"],
            "name": observation["asset"]["name"],
            "size_bytes": observation["asset"]["size_bytes"],
            "digest": live_digest,
        },
    }
    extraction = extract_artifact(
        download_dir=release_download_dir,
        selection=synthetic_selection,
        output_dir=output_dir,
    )
    return {
        "schema_version": 1,
        "kind": "github-release-runtime-input",
        "status": "EXTRACTED",
        "observation": observation,
        "extraction": extraction,
    }


def _validate_promoted_release_source(
    *,
    source_dir: Path,
    release_observation: dict[str, Any],
    expected_repository: str,
    expected_repository_id: int,
    expected_commit: str,
    expected_promotion_workflow: str,
) -> dict[str, Any]:
    provenance = load_json_object(
        source_dir / "source-provenance.json", label="released source provenance"
    )
    deployment = provenance.get("deployment")
    if not isinstance(deployment, dict):
        raise GitHubReleaseRuntimeError("released source lacks deployment metadata")
    promotion_workflow = workflow(
        expected_promotion_workflow, label="expected promotion workflow"
    )
    _require_equal(
        deployment.get("workflow"), promotion_workflow, label="released source workflow"
    )
    promotion_run_id = positive_int(
        deployment.get("run_id"), label="released source promotion run id"
    )
    promotion_run_attempt = positive_int(
        deployment.get("run_attempt"), label="released source promotion run attempt"
    )
    destination = provenance.get("destination")
    if not isinstance(destination, dict):
        raise GitHubReleaseRuntimeError("released source lacks destination metadata")
    _require_equal(
        destination.get("environment"),
        _PROMOTION_ENVIRONMENT,
        label="released source environment",
    )
    _require_equal(
        destination.get("identity"),
        _promotion_identity(expected_repository_id),
        label="released source destination identity",
    )
    validation = validate_production_transition_source(
        source_dir=source_dir,
        expected_repository=expected_repository,
        expected_commit=expected_commit,
        expected_workflow=promotion_workflow,
        expected_run_id=promotion_run_id,
        expected_run_attempt=promotion_run_attempt,
        expected_event="workflow_run",
        expected_branch="main",
        expected_environment=_PROMOTION_ENVIRONMENT,
        expected_destination_id=_promotion_identity(expected_repository_id),
    )
    _require_equal(
        release_observation["repository"],
        expected_repository,
        label="live release repository",
    )
    _require_equal(
        release_observation["source_commit"],
        expected_commit,
        label="live release commit",
    )
    return {
        "status": validation["status"],
        "promotion_workflow": promotion_workflow,
        "promotion_run_id": promotion_run_id,
        "promotion_run_attempt": promotion_run_attempt,
        "source_set_digest": validation["source_set_digest"],
    }


def _write_source_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _source_inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _build_transition_source(
    *,
    output_dir: Path,
    repository_name: str,
    source_commit: str,
    runtime_workflow: str,
    runtime_run_id: int,
    runtime_run_attempt: int,
    repository_id: int,
    release_observation: dict[str, Any],
    wheel: dict[str, Any],
    install: dict[str, Any],
    cli: dict[str, Any],
    runtime_manifest: dict[str, Any],
) -> dict[str, Any]:
    if output_dir.is_symlink() or output_dir.exists():
        raise GitHubReleaseRuntimeError(
            f"runtime source output must not already exist: {output_dir}"
        )
    output = output_dir.resolve(strict=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / "evidence").mkdir()
    runtime_workflow = workflow(runtime_workflow, label="runtime workflow")
    runtime_run_id = positive_int(runtime_run_id, label="runtime run id")
    runtime_run_attempt = positive_int(runtime_run_attempt, label="runtime run attempt")
    destination = {
        "environment": _RUNTIME_ENVIRONMENT,
        "identity": _runtime_identity(repository_id, runtime_run_id, runtime_run_attempt),
    }
    deployment = {
        "workflow": runtime_workflow,
        "run_id": runtime_run_id,
        "run_attempt": runtime_run_attempt,
        "event": "workflow_run",
        "branch": "main",
    }
    release = release_observation["release"]
    asset = release_observation["asset"]
    subject_digest = asset["downloaded_digest"] or asset["api_digest"]
    if subject_digest is None:
        raise GitHubReleaseRuntimeError("live release observation lacks an asset digest")
    release_id = (
        f"runtime/github-release/{release['id']}/{asset['id']}/"
        f"run/{runtime_run_id}/attempt/{runtime_run_attempt}"
    )
    transition_id = (
        f"github/runtime/{source_commit[:12]}/{runtime_run_id}/{runtime_run_attempt}"
    )
    common = {
        "schema_version": 1,
        "transition_id": transition_id,
        "repository": repository_name,
        "source_commit": source_commit,
        "release_id": release_id,
        "destination": destination,
    }
    checks = [
        f"public GitHub Release {release['id']} asset {asset['id']} was downloaded for the exact commit",
        f"live release asset SHA-256 {subject_digest} was verified before extraction",
        f"wheel {wheel['filename']} matched package {wheel['package_name']} version {wheel['package_version']}",
        f"wheel SHA-256 {wheel['sha256']} was recorded before installation",
        "wheel metadata preserved the ibex-av console entry point and Python >=3.11 contract",
        "wheel was installed with --no-index --no-deps into a fresh virtual environment",
        f"isolated Python {install['python_version']} imported the package from the virtual environment",
        f"installed ibex-av verified {cli['files_checked']} exact release-source files with no mismatches",
        f"runtime manifest SHA-256 {runtime_manifest['manifest_sha256']} matched the executed bundle",
        "execution occurred on a GitHub-hosted Ubuntu 24.04 runner and did not claim a customer-controlled host",
    ]
    payloads: dict[str, dict[str, Any]] = {
        "source-provenance.json": {
            "schema_version": 1,
            "kind": "production-transition-source",
            "repository": repository_name,
            "source_commit": source_commit,
            "deployment": deployment,
            "destination": destination,
            "release": {
                "release_id": release_id,
                "subject_digest": subject_digest,
            },
            "claim_boundary": _CLAIM_BOUNDARY,
        },
        "transition-report.json": {
            "schema_version": 1,
            "transition_id": transition_id,
            "status": "VERIFIED",
            "phase": "REFLECT",
            "next_phase": "CONTINUE",
            "issues": [],
            "axes": {
                "time": {"status": "PASS"},
                "intention": {"status": "PASS"},
                "space": {"status": "PASS"},
            },
            "evidence": {
                "intent_ref": "manifest:evidence/intent.json",
                "action_ref": "manifest:evidence/action.json",
                "result_ref": "manifest:evidence/result.json",
                "verification_ref": "manifest:evidence/verification.json",
            },
            "claim_boundary": _CLAIM_BOUNDARY,
        },
        "evidence/intent.json": {
            **common,
            "kind": "production-transition-intent",
            "statement": (
                "Install a wheel built from the exact commit into a fresh isolated "
                "GitHub-hosted virtual environment and execute its ibex-av entry point "
                "against the exact public customer-release bytes."
            ),
        },
        "evidence/action.json": {
            **common,
            "kind": "production-transition-action",
            "deployment": {
                "workflow": runtime_workflow,
                "run_id": runtime_run_id,
                "run_attempt": runtime_run_attempt,
            },
            "subject_digest": subject_digest,
            "status": "COMPLETED",
        },
        "evidence/result.json": {
            **common,
            "kind": "production-transition-result",
            "deployment_id": (
                f"github-actions/runtime/run/{runtime_run_id}/attempt/{runtime_run_attempt}"
            ),
            "subject_digest": subject_digest,
            "status": "SUCCEEDED",
        },
        "evidence/verification.json": {
            **common,
            "kind": "production-transition-verification",
            "subject_digest": subject_digest,
            "observed_destination": destination,
            "status": "VERIFIED",
            "checks": checks,
        },
    }
    for relative, payload in payloads.items():
        _write_source_json(output / relative, payload)
    inventory = _source_inventory(output)
    source_set_digest = hashlib.sha256(
        json.dumps(inventory, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "root": output,
        "transition_id": transition_id,
        "deployment": deployment,
        "destination": destination,
        "release": {"release_id": release_id, "subject_digest": subject_digest},
        "claim_boundary": _CLAIM_BOUNDARY,
        "files": inventory,
        "source_set_digest": f"sha256:{source_set_digest}",
    }


def build_runtime_source(
    *,
    source_dir: Path,
    release: dict[str, Any],
    release_download_dir: Path,
    runtime_bundle_dir: Path,
    runtime_manifest: dict[str, Any],
    wheel_path: Path,
    install_report: dict[str, Any],
    cli_report: dict[str, Any],
    output_dir: Path,
    expected_repository: str,
    expected_repository_id: int,
    expected_commit: str,
    expected_promotion_workflow: str,
    expected_release_tag: str,
    expected_asset_name: str,
    expected_package_version: str,
    runtime_workflow: str,
    runtime_run_id: int,
    runtime_run_attempt: int,
) -> dict[str, Any]:
    repo = repository(expected_repository, label="expected repository")
    repo_id = positive_int(expected_repository_id, label="expected repository id")
    source_commit = text(expected_commit, label="expected commit", maximum=40)
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise GitHubReleaseRuntimeError("expected commit must be 40 lowercase hex")
    downloaded_asset = _single_file(
        release_download_dir, label="live release download directory"
    )
    release_observation = observe_release(
        release=release,
        expected_repository=repo,
        expected_repository_id=repo_id,
        expected_commit=source_commit,
        expected_tag=expected_release_tag,
        expected_asset_name=expected_asset_name,
        downloaded_asset=downloaded_asset,
    )
    promotion = _validate_promoted_release_source(
        source_dir=source_dir,
        release_observation=release_observation,
        expected_repository=repo,
        expected_repository_id=repo_id,
        expected_commit=source_commit,
        expected_promotion_workflow=expected_promotion_workflow,
    )
    package_version = _version(
        expected_package_version, label="expected package version"
    )
    wheel = inspect_wheel(
        wheel_path,
        expected_package_name=_PACKAGE_NAME,
        expected_version=package_version,
    )
    install = validate_install_report(
        install_report,
        expected_package_name=_PACKAGE_NAME,
        expected_version=package_version,
        expected_wheel=wheel,
    )
    cli = validate_cli_report(cli_report)
    manifest = validate_runtime_manifest(
        runtime_manifest, runtime_bundle_dir=runtime_bundle_dir
    )
    runtime_source = _build_transition_source(
        output_dir=output_dir,
        repository_name=repo,
        source_commit=source_commit,
        runtime_workflow=runtime_workflow,
        runtime_run_id=runtime_run_id,
        runtime_run_attempt=runtime_run_attempt,
        repository_id=repo_id,
        release_observation=release_observation,
        wheel=wheel,
        install=install,
        cli=cli,
        runtime_manifest=manifest,
    )
    return {
        "schema_version": 1,
        "kind": "github-release-runtime-source-build",
        "status": "EXECUTED",
        "repository": repo,
        "source_commit": source_commit,
        "input": {
            "release": release_observation,
            "promotion": promotion,
        },
        "runtime": {
            "wheel": wheel,
            "install": install,
            "cli": cli,
            "manifest": manifest,
        },
        "runtime_source": {
            "transition_id": runtime_source["transition_id"],
            "deployment": runtime_source["deployment"],
            "destination": runtime_source["destination"],
            "release": runtime_source["release"],
            "claim_boundary": runtime_source["claim_boundary"],
            "files": runtime_source["files"],
            "source_set_digest": runtime_source["source_set_digest"],
        },
    }


def observe_runtime_source(
    *,
    provenance: dict[str, Any],
    release: dict[str, Any],
    expected_repository: str,
    expected_repository_id: int,
    expected_commit: str,
    expected_runtime_workflow: str,
    expected_runtime_run_id: int,
    expected_runtime_run_attempt: int,
    expected_release_tag: str,
    expected_asset_name: str,
) -> dict[str, Any]:
    repo = repository(expected_repository, label="expected repository")
    repo_id = positive_int(expected_repository_id, label="expected repository id")
    source_commit = text(expected_commit, label="expected commit", maximum=40)
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise GitHubReleaseRuntimeError("expected commit must be 40 lowercase hex")
    runtime_workflow = workflow(
        expected_runtime_workflow, label="expected runtime workflow"
    )
    run_id = positive_int(expected_runtime_run_id, label="expected runtime run id")
    run_attempt = positive_int(
        expected_runtime_run_attempt, label="expected runtime run attempt"
    )
    if provenance.get("schema_version") != 1 or provenance.get("kind") != "production-transition-source":
        raise GitHubReleaseRuntimeError("runtime provenance must be production source v1")
    _require_equal(provenance.get("repository"), repo, label="runtime provenance repository")
    _require_equal(
        provenance.get("source_commit"), source_commit, label="runtime provenance commit"
    )
    deployment = provenance.get("deployment")
    if not isinstance(deployment, dict):
        raise GitHubReleaseRuntimeError("runtime provenance lacks deployment")
    for key, expected in {
        "workflow": runtime_workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "event": "workflow_run",
        "branch": "main",
    }.items():
        _require_equal(deployment.get(key), expected, label=f"runtime deployment {key}")
    release_meta = provenance.get("release")
    if not isinstance(release_meta, dict):
        raise GitHubReleaseRuntimeError("runtime provenance lacks release metadata")
    observation = observe_release(
        release=release,
        expected_repository=repo,
        expected_repository_id=repo_id,
        expected_commit=source_commit,
        expected_tag=expected_release_tag,
        expected_asset_name=expected_asset_name,
        expected_asset_digest=release_meta.get("subject_digest"),
    )
    expected_destination = _runtime_identity(repo_id, run_id, run_attempt)
    destination = provenance.get("destination")
    if not isinstance(destination, dict):
        raise GitHubReleaseRuntimeError("runtime provenance lacks destination")
    _require_equal(
        destination.get("environment"),
        _RUNTIME_ENVIRONMENT,
        label="runtime destination environment",
    )
    _require_equal(
        destination.get("identity"),
        expected_destination,
        label="runtime destination identity",
    )
    claim_boundary = provenance.get("claim_boundary")
    if (
        not isinstance(claim_boundary, str)
        or "not a physical production execution claim" not in claim_boundary
    ):
        raise GitHubReleaseRuntimeError("runtime claim boundary is missing")
    return {
        "schema_version": 1,
        "kind": "github-release-runtime-observation",
        "status": "OBSERVED",
        "repository": repo,
        "source_commit": source_commit,
        "runtime_workflow": runtime_workflow,
        "runtime_run_id": run_id,
        "runtime_run_attempt": run_attempt,
        "destination_id": expected_destination,
        "release": observation,
        "claim_boundary": claim_boundary,
    }


def append_outputs(path: Path, observation: dict[str, Any]) -> None:
    if path.is_symlink() or path.is_dir():
        raise GitHubReleaseRuntimeError(f"GitHub output path is unsafe: {path}")
    values = {
        "destination-id": observation["destination_id"],
        "runtime-run-id": str(observation["runtime_run_id"]),
        "runtime-run-attempt": str(observation["runtime_run_attempt"]),
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            if not value or "\n" in value or "\r" in value:
                raise GitHubReleaseRuntimeError(f"unsafe GitHub output value: {key}")
            handle.write(f"{key}={value}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract, build, or independently observe release runtime evidence"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--release-api-json", type=Path, required=True)
    extract.add_argument("--release-download-dir", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)
    extract.add_argument("--expected-repository", required=True)
    extract.add_argument("--expected-repository-id", type=int, required=True)
    extract.add_argument("--expected-commit", required=True)
    extract.add_argument("--expected-release-tag", required=True)
    extract.add_argument("--expected-asset-name", required=True)
    extract.add_argument("--report", type=Path, required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--release-api-json", type=Path, required=True)
    build.add_argument("--release-download-dir", type=Path, required=True)
    build.add_argument("--runtime-bundle-dir", type=Path, required=True)
    build.add_argument("--runtime-manifest", type=Path, required=True)
    build.add_argument("--wheel", type=Path, required=True)
    build.add_argument("--install-report", type=Path, required=True)
    build.add_argument("--cli-report", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--expected-repository", required=True)
    build.add_argument("--expected-repository-id", type=int, required=True)
    build.add_argument("--expected-commit", required=True)
    build.add_argument("--expected-promotion-workflow", required=True)
    build.add_argument("--expected-release-tag", required=True)
    build.add_argument("--expected-asset-name", required=True)
    build.add_argument("--expected-package-version", required=True)
    build.add_argument("--runtime-workflow", required=True)
    build.add_argument("--runtime-run-id", type=int, required=True)
    build.add_argument("--runtime-run-attempt", type=int, required=True)
    build.add_argument("--report", type=Path, required=True)

    observe = subparsers.add_parser("observe")
    observe.add_argument("--source-provenance", type=Path, required=True)
    observe.add_argument("--release-api-json", type=Path, required=True)
    observe.add_argument("--expected-repository", required=True)
    observe.add_argument("--expected-repository-id", type=int, required=True)
    observe.add_argument("--expected-commit", required=True)
    observe.add_argument("--expected-runtime-workflow", required=True)
    observe.add_argument("--expected-runtime-run-id", type=int, required=True)
    observe.add_argument("--expected-runtime-run-attempt", type=int, required=True)
    observe.add_argument("--expected-release-tag", required=True)
    observe.add_argument("--expected-asset-name", required=True)
    observe.add_argument("--github-output", type=Path, required=True)
    observe.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        release = load_json_object(args.release_api_json, label="GitHub release API response")
        if args.command == "extract":
            result = extract_live_release(
                release=release,
                release_download_dir=args.release_download_dir,
                output_dir=args.output_dir,
                expected_repository=args.expected_repository,
                expected_repository_id=args.expected_repository_id,
                expected_commit=args.expected_commit,
                expected_release_tag=args.expected_release_tag,
                expected_asset_name=args.expected_asset_name,
            )
            write_json(args.report, result, forbidden_root=args.output_dir)
        elif args.command == "build":
            result = build_runtime_source(
                source_dir=args.source_dir,
                release=release,
                release_download_dir=args.release_download_dir,
                runtime_bundle_dir=args.runtime_bundle_dir,
                runtime_manifest=load_json_object(
                    args.runtime_manifest, label="runtime manifest"
                ),
                wheel_path=args.wheel,
                install_report=load_json_object(
                    args.install_report, label="runtime install report"
                ),
                cli_report=load_json_object(
                    args.cli_report, label="installed CLI report"
                ),
                output_dir=args.output_dir,
                expected_repository=args.expected_repository,
                expected_repository_id=args.expected_repository_id,
                expected_commit=args.expected_commit,
                expected_promotion_workflow=args.expected_promotion_workflow,
                expected_release_tag=args.expected_release_tag,
                expected_asset_name=args.expected_asset_name,
                expected_package_version=args.expected_package_version,
                runtime_workflow=args.runtime_workflow,
                runtime_run_id=args.runtime_run_id,
                runtime_run_attempt=args.runtime_run_attempt,
            )
            write_json(args.report, result, forbidden_root=args.output_dir)
        else:
            result = observe_runtime_source(
                provenance=load_json_object(
                    args.source_provenance, label="runtime source provenance"
                ),
                release=release,
                expected_repository=args.expected_repository,
                expected_repository_id=args.expected_repository_id,
                expected_commit=args.expected_commit,
                expected_runtime_workflow=args.expected_runtime_workflow,
                expected_runtime_run_id=args.expected_runtime_run_id,
                expected_runtime_run_attempt=args.expected_runtime_run_attempt,
                expected_release_tag=args.expected_release_tag,
                expected_asset_name=args.expected_asset_name,
            )
            write_json(args.report, result)
            append_outputs(args.github_output, result)
    except (
        OSError,
        GitHubReleaseProductionError,
        ProductionTransitionSourceError,
        TrustedTransitionArtifactError,
        GitHubReleaseRuntimeError,
        ValueError,
    ) as error:
        print(f"GitHub release runtime source error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
