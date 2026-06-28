#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.trusted_transition_artifact import (
        TrustedTransitionArtifactError,
        _canonical_zip_name,
        _copy_limited,
        _validate_zip_mode,
        commit,
        digest,
        load_json_object,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
    )
except ImportError:
    from trusted_transition_artifact import (
        TrustedTransitionArtifactError,
        _canonical_zip_name,
        _copy_limited,
        _validate_zip_mode,
        commit,
        digest,
        load_json_object,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
    )


class IbexEvidencePromotionError(ValueError):
    """Raised when an Ibex E2E artifact cannot be promoted safely."""


_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 96 * 1024 * 1024
_MAX_ENTRIES = 128
_ALLOWED_ROOT_FILES = {
    "commands.sh",
    "manifest.json",
    "timing-exit-code.txt",
    "tool-versions.txt",
}
_ALLOWED_DIRECTORIES = {"logs", "normalized", "raw"}
_REQUIRED_EVIDENCE_FILES = {
    "commands.sh",
    "normalized/architectural.jsonl",
    "normalized/causal-report.json",
    "normalized/metadata.jsonl",
    "normalized/parser-report.json",
    "normalized/timing-causal.jsonl",
    "normalized/timing-report.json",
    "normalized/timing.jsonl",
    "raw/hello_test.elf",
    "raw/ibex_simple_system.log",
    "raw/sim.fst",
    "raw/simulator.stdout",
    "raw/trace_core_00000000.log",
    "timing-exit-code.txt",
    "tool-versions.txt",
}
_E2E_MANIFEST_KEYS = {
    "schema_version",
    "generated_at_utc",
    "project",
    "dut",
    "result",
    "tool_versions",
    "commands_file",
    "files",
}
_PROJECT_KEYS = {"repository", "commit"}
_DUT_KEYS = {
    "configuration",
    "program",
    "repository",
    "requested_ref",
    "resolved_commit",
    "simulator",
}
_RESULT_KEYS = {
    "simulation_exit_code",
    "timing_analyzer_exit_code",
    "timing_anomaly_detected",
    "trace_parse_status",
}
_FILE_KEYS = {"path", "size_bytes", "sha256"}
_CLAIM_BOUNDARY = (
    "This verified transition proves that the exact main-branch commit's pinned "
    "Ibex Verilator evidence artifact was integrity-checked and promoted into the "
    "repository-bound ibex-evidence-release environment. It does not prove physical "
    "hardware behavior, customer deployment, or application correctness, and it is "
    "not a production deployment claim."
)


def _exact_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise IbexEvidencePromotionError(
            f"{label} keys mismatch; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _require_equal(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise IbexEvidencePromotionError(
            f"{label} mismatch: expected {expected!r}, got {actual!r}"
        )


def _safe_output_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink() or path.exists():
        raise IbexEvidencePromotionError(f"{label} must not already exist: {path}")
    resolved = path.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _safe_report_path(path: Path, *, forbidden_roots: tuple[Path, ...]) -> Path:
    if path.is_symlink() or path.is_dir():
        raise IbexEvidencePromotionError(
            f"report must be a writable regular-file path: {path}"
        )
    resolved = path.resolve(strict=False)
    for root in forbidden_roots:
        if resolved.is_relative_to(root.resolve(strict=True)):
            raise IbexEvidencePromotionError(
                "promotion report must be outside extracted and source directories"
            )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _allowed_archive_file(path: str) -> bool:
    if path in _ALLOWED_ROOT_FILES:
        return True
    parts = PurePosixPath(path).parts
    return len(parts) >= 2 and parts[0] in _ALLOWED_DIRECTORIES


def _selection_identity(
    selection: dict[str, Any],
    *,
    expected_repository: str,
    expected_commit: str,
    expected_workflow: str,
    expected_run_id: int,
    expected_run_attempt: int,
) -> dict[str, Any]:
    if selection.get("schema_version") != 1 or selection.get("status") != "SELECTED":
        raise IbexEvidencePromotionError("upstream artifact selection must be SELECTED")
    repo = repository(expected_repository, label="expected repository")
    source_commit = commit(expected_commit, label="expected commit")
    workflow_path = workflow(expected_workflow, label="expected E2E workflow")
    run_id = positive_int(expected_run_id, label="expected E2E run id")
    run_attempt = positive_int(
        expected_run_attempt, label="expected E2E run attempt"
    )
    for key, expected in {
        "repository": repo,
        "head_sha": source_commit,
        "head_branch": "main",
        "workflow": workflow_path,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }.items():
        _require_equal(selection.get(key), expected, label=f"selection {key}")
    artifact = selection.get("artifact")
    if not isinstance(artifact, dict):
        raise IbexEvidencePromotionError("selection lacks artifact metadata")
    expected_name = f"ibex-verilator-evidence-{source_commit}"
    _require_equal(artifact.get("name"), expected_name, label="E2E artifact name")
    artifact_id = positive_int(artifact.get("id"), label="E2E artifact id")
    artifact_digest = digest(artifact.get("digest"), label="E2E artifact digest")
    size_bytes = positive_int(artifact.get("size_bytes"), label="E2E artifact size")
    if size_bytes > _MAX_ARCHIVE_BYTES:
        raise IbexEvidencePromotionError("E2E artifact exceeds archive size limit")
    return {
        "repository": repo,
        "source_commit": source_commit,
        "workflow": workflow_path,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifact": {
            "id": artifact_id,
            "name": expected_name,
            "digest": artifact_digest,
            "size_bytes": size_bytes,
        },
    }


def _extract_archive(
    *,
    download_dir: Path,
    expected_digest: str,
    extracted_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    if download_dir.is_symlink():
        raise IbexEvidencePromotionError("download directory must not be a symlink")
    download_root = download_dir.resolve(strict=True)
    if not download_root.is_dir():
        raise IbexEvidencePromotionError("download path must be a directory")
    entries = list(download_root.iterdir())
    if len(entries) != 1:
        raise IbexEvidencePromotionError(
            "download directory must contain exactly one raw artifact archive"
        )
    archive = entries[0]
    if archive.is_symlink() or not archive.is_file():
        raise IbexEvidencePromotionError("downloaded artifact must be a regular file")
    archive_size = archive.stat().st_size
    if archive_size <= 0 or archive_size > _MAX_ARCHIVE_BYTES:
        raise IbexEvidencePromotionError("downloaded archive size is unsafe")
    actual_digest = f"sha256:{sha256_file(archive)}"
    _require_equal(actual_digest, expected_digest, label="downloaded archive digest")

    output = _safe_output_directory(extracted_dir, label="extraction directory")
    if output.is_relative_to(download_root) or download_root.is_relative_to(output):
        raise IbexEvidencePromotionError(
            "download and extraction directories must not contain each other"
        )

    extracted: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(archive, "r") as zipped:
            infos = zipped.infolist()
            if not infos or len(infos) > _MAX_ENTRIES:
                raise IbexEvidencePromotionError(
                    f"archive must contain between 1 and {_MAX_ENTRIES} entries"
                )
            seen: set[str] = set()
            folded: set[str] = set()
            total_uncompressed = 0
            validated: list[tuple[zipfile.ZipInfo, str, bool]] = []
            for info in infos:
                name, is_directory = _canonical_zip_name(info)
                key = name.casefold()
                if name in seen or key in folded:
                    raise IbexEvidencePromotionError(
                        f"archive contains duplicate or case-colliding path: {name}"
                    )
                seen.add(name)
                folded.add(key)
                _validate_zip_mode(info, is_directory=is_directory)
                if is_directory:
                    if name not in _ALLOWED_DIRECTORIES:
                        raise IbexEvidencePromotionError(
                            f"archive contains unexpected directory entry: {name}"
                        )
                else:
                    if not _allowed_archive_file(name):
                        raise IbexEvidencePromotionError(
                            f"archive contains path outside the E2E layout: {name}"
                        )
                    if info.file_size < 0 or info.file_size > _MAX_FILE_BYTES:
                        raise IbexEvidencePromotionError(
                            f"archive member size is unsafe: {name}"
                        )
                    total_uncompressed += info.file_size
                    if total_uncompressed > _MAX_TOTAL_BYTES:
                        raise IbexEvidencePromotionError(
                            "archive total uncompressed size exceeds limit"
                        )
                validated.append((info, name, is_directory))

            for info, name, is_directory in validated:
                destination = output / name
                if not destination.resolve(strict=False).is_relative_to(output):
                    raise IbexEvidencePromotionError(
                        f"archive member escapes extraction root: {name}"
                    )
                if is_directory:
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(info, "r") as source, destination.open("xb") as target:
                    written = _copy_limited(
                        source,
                        target,
                        limit=_MAX_FILE_BYTES,
                        label=f"archive member {name}",
                    )
                if written != info.file_size:
                    raise IbexEvidencePromotionError(
                        f"archive member size changed during extraction: {name}"
                    )
                extracted.append(
                    {
                        "path": name,
                        "size_bytes": written,
                        "sha256": sha256_file(destination),
                    }
                )
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise IbexEvidencePromotionError(
            f"unable to safely extract E2E artifact: {error}"
        ) from error

    extracted.sort(key=lambda item: item["path"])
    return output, {
        "filename": archive.name,
        "size_bytes": archive_size,
        "digest": actual_digest,
        "entries": extracted,
    }


def _manifest_inventory(
    *,
    root: Path,
    manifest: dict[str, Any],
    extracted_files: set[str],
) -> tuple[dict[str, dict[str, Any]], int]:
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > _MAX_ENTRIES:
        raise IbexEvidencePromotionError("E2E manifest files must be a non-empty array")
    inventory: dict[str, dict[str, Any]] = {}
    total = 0
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise IbexEvidencePromotionError(
                f"E2E manifest files[{index}] must be an object"
            )
        _exact_keys(item, _FILE_KEYS, label=f"E2E manifest files[{index}]")
        path = text(item["path"], label=f"E2E manifest files[{index}].path")
        pure = PurePosixPath(path)
        if (
            pure.as_posix() != path
            or path == "manifest.json"
            or not _allowed_archive_file(path)
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise IbexEvidencePromotionError(
                f"E2E manifest contains unsafe path: {path}"
            )
        if path in inventory or path.casefold() in {
            existing.casefold() for existing in inventory
        }:
            raise IbexEvidencePromotionError(
                f"E2E manifest contains duplicate or case-colliding path: {path}"
            )
        size_bytes = positive_int(
            item["size_bytes"], label=f"E2E manifest files[{index}].size_bytes"
        )
        expected_digest = digest(
            f"sha256:{item['sha256']}",
            label=f"E2E manifest files[{index}].sha256",
        )
        target = root / path
        if target.is_symlink() or not target.is_file():
            raise IbexEvidencePromotionError(
                f"E2E manifest path is not a regular extracted file: {path}"
            )
        _require_equal(target.stat().st_size, size_bytes, label=f"size for {path}")
        actual_digest = f"sha256:{sha256_file(target)}"
        _require_equal(actual_digest, expected_digest, label=f"digest for {path}")
        inventory[path] = {
            "path": path,
            "size_bytes": size_bytes,
            "sha256": actual_digest.removeprefix("sha256:"),
        }
        total += size_bytes
        if total > _MAX_TOTAL_BYTES:
            raise IbexEvidencePromotionError(
                "E2E manifest total size exceeds promotion limit"
            )

    expected_extracted = set(inventory) | {"manifest.json"}
    if extracted_files != expected_extracted:
        raise IbexEvidencePromotionError(
            "E2E archive and manifest inventory differ; "
            f"missing={sorted(expected_extracted - extracted_files)}, "
            f"unexpected={sorted(extracted_files - expected_extracted)}"
        )
    missing_required = _REQUIRED_EVIDENCE_FILES - set(inventory)
    if missing_required:
        raise IbexEvidencePromotionError(
            f"E2E artifact lacks required evidence files: {sorted(missing_required)}"
        )
    return inventory, total


def _validate_e2e_evidence(
    *,
    root: Path,
    expected_repository: str,
    expected_commit: str,
    expected_ibex_ref: str,
    extracted_files: set[str],
) -> dict[str, Any]:
    manifest = load_json_object(root / "manifest.json", label="Ibex E2E manifest")
    _exact_keys(manifest, _E2E_MANIFEST_KEYS, label="Ibex E2E manifest")
    if manifest.get("schema_version") != 1:
        raise IbexEvidencePromotionError("Ibex E2E manifest schema_version must equal 1")
    text(manifest.get("generated_at_utc"), label="E2E generated_at_utc")
    _require_equal(manifest.get("commands_file"), "commands.sh", label="commands file")

    project = manifest.get("project")
    if not isinstance(project, dict):
        raise IbexEvidencePromotionError("E2E project must be an object")
    _exact_keys(project, _PROJECT_KEYS, label="E2E project")
    _require_equal(project.get("repository"), expected_repository, label="project repository")
    _require_equal(project.get("commit"), expected_commit, label="project commit")

    dut = manifest.get("dut")
    if not isinstance(dut, dict):
        raise IbexEvidencePromotionError("E2E DUT must be an object")
    _exact_keys(dut, _DUT_KEYS, label="E2E DUT")
    for key, expected in {
        "repository": "lowRISC/ibex",
        "requested_ref": expected_ibex_ref,
        "resolved_commit": expected_ibex_ref,
        "configuration": "small",
        "simulator": "verilator",
        "program": "examples/sw/simple_system/hello_test/hello_test.elf",
    }.items():
        _require_equal(dut.get(key), expected, label=f"DUT {key}")

    result = manifest.get("result")
    if not isinstance(result, dict):
        raise IbexEvidencePromotionError("E2E result must be an object")
    _exact_keys(result, _RESULT_KEYS, label="E2E result")
    _require_equal(result.get("simulation_exit_code"), 0, label="simulation exit code")
    _require_equal(result.get("trace_parse_status"), "PARSED", label="trace parse status")
    timing_exit = result.get("timing_analyzer_exit_code")
    if isinstance(timing_exit, bool) or timing_exit not in {0, 1}:
        raise IbexEvidencePromotionError(
            "timing analyzer exit code must be 0 or 1"
        )
    anomaly = result.get("timing_anomaly_detected")
    if not isinstance(anomaly, bool) or anomaly != (timing_exit == 1):
        raise IbexEvidencePromotionError(
            "timing anomaly flag must match timing analyzer exit code"
        )
    tool_versions = manifest.get("tool_versions")
    if not isinstance(tool_versions, dict) or not tool_versions:
        raise IbexEvidencePromotionError("E2E tool_versions must be a non-empty object")
    if "verilator" not in tool_versions or "python" not in tool_versions:
        raise IbexEvidencePromotionError(
            "E2E tool_versions must identify Verilator and Python"
        )

    inventory, total_size = _manifest_inventory(
        root=root,
        manifest=manifest,
        extracted_files=extracted_files,
    )

    parser = load_json_object(
        root / "normalized/parser-report.json", label="Ibex parser report"
    )
    _require_equal(parser.get("status"), "PARSED", label="parser report status")
    instructions = positive_int(parser.get("instructions"), label="parsed instructions")
    _require_equal(
        parser.get("source_sha256"),
        inventory["raw/trace_core_00000000.log"]["sha256"],
        label="parser source digest",
    )

    causal = load_json_object(
        root / "normalized/causal-report.json", label="Ibex causal report"
    )
    _require_equal(causal.get("status"), "ENRICHED", label="causal report status")
    _require_equal(causal.get("alignment_ratio"), 1.0, label="causal alignment ratio")
    retirement_times = positive_int(
        causal.get("retirement_times"), label="causal retirement times"
    )
    _require_equal(
        causal.get("matched_retirement_times"),
        retirement_times,
        label="matched retirement times",
    )
    timing_samples = positive_int(
        causal.get("timing_samples"), label="causal timing samples"
    )
    _require_equal(
        causal.get("missing_optional_signals"),
        [],
        label="missing optional signals",
    )

    hello_log = (root / "raw/ibex_simple_system.log").read_text(encoding="utf-8")
    for marker in ("Hello simple system", "DEADBEEF", "BAADF00D", "Tick!", "Tock!"):
        if marker not in hello_log:
            raise IbexEvidencePromotionError(
                f"Ibex simulation log lacks expected marker: {marker}"
            )
    simulator_stdout = (root / "raw/simulator.stdout").read_text(encoding="utf-8")
    for marker in (
        "Simulation of Ibex",
        "Terminating simulation by software request.",
        "Received $finish() from Verilog",
    ):
        if marker not in simulator_stdout:
            raise IbexEvidencePromotionError(
                f"simulator stdout lacks expected completion marker: {marker}"
            )
    try:
        recorded_timing_exit = int(
            (root / "timing-exit-code.txt").read_text(encoding="utf-8").strip()
        )
    except ValueError as error:
        raise IbexEvidencePromotionError(
            "timing-exit-code.txt must contain one integer"
        ) from error
    _require_equal(recorded_timing_exit, timing_exit, label="recorded timing exit code")

    return {
        "manifest": manifest,
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "files_verified": len(inventory),
        "total_size_bytes": total_size,
        "instructions": instructions,
        "retirement_times": retirement_times,
        "timing_samples": timing_samples,
        "timing_anomaly_detected": anomaly,
        "timing_analyzer_exit_code": timing_exit,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _source_inventory(root: Path) -> list[dict[str, Any]]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(files)
    ]


def _build_transition_source(
    *,
    output_dir: Path,
    repository_name: str,
    source_commit: str,
    promotion_workflow: str,
    promotion_run_id: int,
    promotion_run_attempt: int,
    promotion_event: str,
    branch: str,
    destination_environment: str,
    destination_id: str,
    upstream: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    output = _safe_output_directory(output_dir, label="transition source directory")
    (output / "evidence").mkdir()
    promotion_workflow = workflow(promotion_workflow, label="promotion workflow")
    promotion_run_id = positive_int(promotion_run_id, label="promotion run id")
    promotion_run_attempt = positive_int(
        promotion_run_attempt, label="promotion run attempt"
    )
    promotion_event = text(promotion_event, label="promotion event", maximum=100)
    branch = text(branch, label="promotion branch", maximum=200)
    destination_environment = text(
        destination_environment, label="destination environment", maximum=200
    )
    destination_id = text(destination_id, label="destination identity", maximum=500)

    short = source_commit[:12]
    release_id = (
        f"ibex-evidence-{short}-{upstream['run_id']}-{upstream['run_attempt']}"
    )
    transition_id = (
        f"ibex/evidence-promotion/{short}/{promotion_run_id}/{promotion_run_attempt}"
    )
    destination = {
        "environment": destination_environment,
        "identity": destination_id,
    }
    deployment = {
        "workflow": promotion_workflow,
        "run_id": promotion_run_id,
        "run_attempt": promotion_run_attempt,
        "event": promotion_event,
        "branch": branch,
    }
    subject_digest = upstream["artifact"]["digest"]
    common = {
        "schema_version": 1,
        "transition_id": transition_id,
        "repository": repository_name,
        "source_commit": source_commit,
        "release_id": release_id,
        "destination": destination,
    }
    checks = [
        "source artifact SHA-256 matched GitHub artifact metadata",
        f"evidence manifest verified {evidence['files_verified']} listed files with no extras",
        "project commit matched the trusted Ibex E2E workflow head SHA",
        f"pinned Ibex commit {evidence['manifest']['dut']['resolved_commit']} matched requested and resolved refs",
        "Verilator simulation exited successfully and emitted expected hello markers",
        f"trace parser reported PARSED with {evidence['instructions']} instructions",
        f"causal enrichment reported ENRICHED with {evidence['retirement_times']} fully aligned retirement times",
        "timing analyzer outcome was preserved as evidence without asserting timing correctness",
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
                "Promote one exact, integrity-verified Ibex Verilator E2E evidence "
                "artifact into the repository-bound ibex-evidence-release environment."
            ),
        },
        "evidence/action.json": {
            **common,
            "kind": "production-transition-action",
            "deployment": {
                "workflow": promotion_workflow,
                "run_id": promotion_run_id,
                "run_attempt": promotion_run_attempt,
            },
            "subject_digest": subject_digest,
            "status": "COMPLETED",
        },
        "evidence/result.json": {
            **common,
            "kind": "production-transition-result",
            "deployment_id": (
                f"github-actions/run/{promotion_run_id}/attempt/{promotion_run_attempt}"
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
        _write_json(output / relative, payload)

    inventory = _source_inventory(output)
    source_set_digest = hashlib.sha256(
        json.dumps(inventory, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "source_root": output,
        "deployment": deployment,
        "destination": destination,
        "release": {
            "release_id": release_id,
            "subject_digest": subject_digest,
        },
        "transition_id": transition_id,
        "claim_boundary": _CLAIM_BOUNDARY,
        "files": inventory,
        "source_set_digest": f"sha256:{source_set_digest}",
    }


def promote_ibex_evidence(
    *,
    download_dir: Path,
    selection: dict[str, Any],
    extracted_dir: Path,
    output_dir: Path,
    repository_name: str,
    source_commit: str,
    expected_e2e_workflow: str,
    expected_e2e_run_id: int,
    expected_e2e_run_attempt: int,
    expected_ibex_ref: str,
    promotion_workflow: str,
    promotion_run_id: int,
    promotion_run_attempt: int,
    promotion_event: str,
    branch: str,
    destination_environment: str,
    destination_id: str,
) -> dict[str, Any]:
    repo = repository(repository_name, label="repository")
    source_sha = commit(source_commit, label="source commit")
    ibex_ref = commit(expected_ibex_ref, label="expected Ibex ref")
    upstream = _selection_identity(
        selection,
        expected_repository=repo,
        expected_commit=source_sha,
        expected_workflow=expected_e2e_workflow,
        expected_run_id=expected_e2e_run_id,
        expected_run_attempt=expected_e2e_run_attempt,
    )
    extracted_root, archive = _extract_archive(
        download_dir=download_dir,
        expected_digest=upstream["artifact"]["digest"],
        extracted_dir=extracted_dir,
    )
    extracted_files = {item["path"] for item in archive["entries"]}
    evidence = _validate_e2e_evidence(
        root=extracted_root,
        expected_repository=repo,
        expected_commit=source_sha,
        expected_ibex_ref=ibex_ref,
        extracted_files=extracted_files,
    )
    source = _build_transition_source(
        output_dir=output_dir,
        repository_name=repo,
        source_commit=source_sha,
        promotion_workflow=promotion_workflow,
        promotion_run_id=promotion_run_id,
        promotion_run_attempt=promotion_run_attempt,
        promotion_event=promotion_event,
        branch=branch,
        destination_environment=destination_environment,
        destination_id=destination_id,
        upstream=upstream,
        evidence=evidence,
    )
    return {
        "schema_version": 1,
        "kind": "ibex-evidence-promotion",
        "status": "PROMOTED",
        "repository": repo,
        "source_commit": source_sha,
        "upstream": {
            "workflow": upstream["workflow"],
            "run_id": upstream["run_id"],
            "run_attempt": upstream["run_attempt"],
            "artifact": upstream["artifact"],
            "archive": {
                "filename": archive["filename"],
                "size_bytes": archive["size_bytes"],
                "digest": archive["digest"],
            },
            "evidence_manifest_sha256": evidence["manifest_sha256"],
            "files_verified": evidence["files_verified"],
            "total_size_bytes": evidence["total_size_bytes"],
        },
        "observation": {
            "dut_repository": evidence["manifest"]["dut"]["repository"],
            "dut_commit": evidence["manifest"]["dut"]["resolved_commit"],
            "simulator": evidence["manifest"]["dut"]["simulator"],
            "simulation_exit_code": 0,
            "trace_parse_status": "PARSED",
            "instructions": evidence["instructions"],
            "retirement_times": evidence["retirement_times"],
            "timing_samples": evidence["timing_samples"],
            "timing_anomaly_detected": evidence["timing_anomaly_detected"],
            "timing_analyzer_exit_code": evidence["timing_analyzer_exit_code"],
        },
        "deployment": source["deployment"],
        "destination": source["destination"],
        "release": source["release"],
        "transition_id": source["transition_id"],
        "claim_boundary": source["claim_boundary"],
        "source_files": source["files"],
        "source_set_digest": source["source_set_digest"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely promote one exact Ibex Verilator E2E artifact into a production "
            "transition-source contract"
        )
    )
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--extracted-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--expected-e2e-workflow", required=True)
    parser.add_argument("--expected-e2e-run-id", type=int, required=True)
    parser.add_argument("--expected-e2e-run-attempt", type=int, required=True)
    parser.add_argument("--expected-ibex-ref", required=True)
    parser.add_argument("--promotion-workflow", required=True)
    parser.add_argument("--promotion-run-id", type=int, required=True)
    parser.add_argument("--promotion-run-attempt", type=int, required=True)
    parser.add_argument("--promotion-event", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--destination-environment", required=True)
    parser.add_argument("--destination-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selection = load_json_object(args.selection, label="E2E artifact selection")
        result = promote_ibex_evidence(
            download_dir=args.download_dir,
            selection=selection,
            extracted_dir=args.extracted_dir,
            output_dir=args.output_dir,
            repository_name=args.repository,
            source_commit=args.source_commit,
            expected_e2e_workflow=args.expected_e2e_workflow,
            expected_e2e_run_id=args.expected_e2e_run_id,
            expected_e2e_run_attempt=args.expected_e2e_run_attempt,
            expected_ibex_ref=args.expected_ibex_ref,
            promotion_workflow=args.promotion_workflow,
            promotion_run_id=args.promotion_run_id,
            promotion_run_attempt=args.promotion_run_attempt,
            promotion_event=args.promotion_event,
            branch=args.branch,
            destination_environment=args.destination_environment,
            destination_id=args.destination_id,
        )
        report_path = _safe_report_path(
            args.report,
            forbidden_roots=(args.extracted_dir, args.output_dir),
        )
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        OSError,
        RuntimeError,
        TrustedTransitionArtifactError,
        IbexEvidencePromotionError,
        ValueError,
    ) as error:
        print(f"Ibex evidence promotion error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
