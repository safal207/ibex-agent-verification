from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


class EvidenceError(ValueError):
    """Raised when an evidence bundle cannot be described or verified safely."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of one regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_key_value_file(path: Path) -> dict[str, str]:
    """Parse a strict unique-key ``key=value`` metadata file."""
    values: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        if "=" not in line:
            raise EvidenceError(f"{path}:{line_number}: expected key=value")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise EvidenceError(f"{path}:{line_number}: empty key")
        if key in values:
            raise EvidenceError(f"{path}:{line_number}: duplicate key {key!r}")
        values[key] = value.strip()
    return values


def collect_files(evidence_dir: Path, output: Path) -> list[dict[str, Any]]:
    """Collect deterministic manifest entries, excluding the manifest output."""
    files: list[dict[str, Any]] = []
    output_resolved = output.resolve()
    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file() or path.resolve() == output_resolved:
            continue
        files.append(
            {
                "path": path.relative_to(evidence_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return files


def build_manifest(
    *,
    evidence_dir: Path,
    output: Path,
    project_sha: str,
    ibex_requested_ref: str,
    ibex_resolved_sha: str,
    ibex_config: str,
    timing_exit_code: int,
    tool_versions_file: Path,
    commands_file: Path,
) -> dict[str, Any]:
    """Build the deterministic Ibex execution manifest payload."""
    if not evidence_dir.is_dir():
        raise EvidenceError(f"evidence directory does not exist: {evidence_dir}")
    if not tool_versions_file.is_file():
        raise EvidenceError(f"tool versions file does not exist: {tool_versions_file}")
    if not commands_file.is_file():
        raise EvidenceError(f"commands file does not exist: {commands_file}")
    if timing_exit_code not in {0, 1}:
        raise EvidenceError("timing analyzer exit code must be 0 or 1")

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": {
            "repository": "safal207/ibex-agent-verification",
            "commit": project_sha,
        },
        "dut": {
            "repository": "lowRISC/ibex",
            "requested_ref": ibex_requested_ref,
            "resolved_commit": ibex_resolved_sha,
            "configuration": ibex_config,
            "simulator": "verilator",
            "program": "examples/sw/simple_system/hello_test/hello_test.elf",
        },
        "result": {
            "simulation_exit_code": 0,
            "trace_parse_status": "PARSED",
            "timing_analyzer_exit_code": timing_exit_code,
            "timing_anomaly_detected": timing_exit_code == 1,
        },
        "tool_versions": parse_key_value_file(tool_versions_file),
        "commands_file": commands_file.relative_to(evidence_dir).as_posix(),
        "files": collect_files(evidence_dir, output),
    }


def write_manifest(**kwargs: Any) -> dict[str, Any]:
    """Build and persist an Ibex evidence manifest."""
    output = Path(kwargs["output"])
    manifest = build_manifest(**kwargs)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{path}: invalid JSON: {exc.msg}") from exc
    except OSError as exc:
        raise EvidenceError(f"cannot read evidence manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EvidenceError("evidence manifest must be a JSON object")
    if raw.get("schema_version") != 1:
        raise EvidenceError("evidence manifest schema_version must be 1")
    if not isinstance(raw.get("files"), list):
        raise EvidenceError("evidence manifest files must be an array")
    return raw


def _manifest_relative_path(value: Any, *, index: int) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"manifest files[{index}].path must be a non-empty string")
    if "\\" in value:
        raise EvidenceError(
            f"manifest files[{index}].path must use POSIX separators: {value!r}"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise EvidenceError(
            f"manifest files[{index}].path must be canonical and relative: {value!r}"
        )
    return path


def _manifest_non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceError(f"{field} must be a non-negative integer")
    return value


def _source_set_digest(entries: list[dict[str, Any]]) -> str:
    canonical = [
        {
            "path": entry["path"],
            "size_bytes": entry["size_bytes"],
            "sha256": entry["sha256"],
        }
        for entry in sorted(entries, key=lambda item: item["path"])
    ]
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def verify_manifest(*, evidence_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """Verify that a bundle exactly matches its manifest inventory.

    The manifest itself is intentionally excluded because it cannot contain a stable
    hash of itself. Every other regular file must be listed exactly once. Symlinks and
    paths that escape the evidence root are rejected rather than followed. The report
    binds both the manifest bytes and the canonical source inventory.
    """

    try:
        root = evidence_dir.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError(f"evidence directory does not exist: {evidence_dir}") from exc
    if not root.is_dir():
        raise EvidenceError(f"evidence directory is not a directory: {evidence_dir}")

    if manifest_path.is_symlink():
        raise EvidenceError(f"evidence manifest must not be a symlink: {manifest_path}")
    try:
        manifest = manifest_path.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError(f"evidence manifest does not exist: {manifest_path}") from exc
    if not manifest.is_file():
        raise EvidenceError(f"evidence manifest is not a regular file: {manifest_path}")
    if not manifest.is_relative_to(root):
        raise EvidenceError("evidence manifest must be inside the evidence directory")

    payload = _load_manifest(manifest)
    entries = payload["files"]
    listed: set[str] = set()
    normalized_entries: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise EvidenceError(f"manifest files[{index}] must be an object")
        relative = _manifest_relative_path(entry.get("path"), index=index)
        relative_text = relative.as_posix()
        if relative_text in listed:
            raise EvidenceError(f"manifest contains duplicate path: {relative_text}")
        listed.add(relative_text)

        expected_size = _manifest_non_negative_int(
            entry.get("size_bytes"), field=f"manifest files[{index}].size_bytes"
        )
        expected_sha = entry.get("sha256")
        if not isinstance(expected_sha, str) or _SHA256_RE.fullmatch(expected_sha) is None:
            raise EvidenceError(
                f"manifest files[{index}].sha256 must be 64 lowercase hexadecimal characters"
            )
        normalized_entries.append(
            {
                "path": relative_text,
                "size_bytes": expected_size,
                "sha256": expected_sha,
            }
        )

        candidate = root.joinpath(*relative.parts)
        if candidate == manifest:
            raise EvidenceError("evidence manifest cannot list itself")
        if not candidate.exists():
            mismatches.append({"path": relative_text, "problem": "MISSING"})
            continue
        if candidate.is_symlink() or not candidate.is_file():
            raise EvidenceError(f"manifest path is not a regular file: {relative_text}")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise EvidenceError(f"manifest path escapes evidence directory: {relative_text}")

        actual_size = candidate.stat().st_size
        actual_sha = sha256_file(candidate)
        if actual_size != expected_size:
            mismatches.append(
                {
                    "path": relative_text,
                    "problem": "SIZE_MISMATCH",
                    "expected": expected_size,
                    "actual": actual_size,
                }
            )
        if actual_sha != expected_sha:
            mismatches.append(
                {
                    "path": relative_text,
                    "problem": "SHA256_MISMATCH",
                    "expected": expected_sha,
                    "actual": actual_sha,
                }
            )

    actual_files: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise EvidenceError(
                f"evidence bundle contains a symlink: {candidate.relative_to(root).as_posix()}"
            )
        if candidate.is_file() and candidate.resolve() != manifest:
            actual_files.add(candidate.relative_to(root).as_posix())

    unlisted = sorted(actual_files - listed)
    for relative_text in unlisted:
        mismatches.append({"path": relative_text, "problem": "UNLISTED"})

    return {
        "status": "VERIFIED" if not mismatches else "INTEGRITY_MISMATCH",
        "schema_version": payload["schema_version"],
        "files_checked": len(entries),
        "mismatches": mismatches,
        "manifest_sha256": f"sha256:{sha256_file(manifest)}",
        "source_set_digest": f"sha256:{_source_set_digest(normalized_entries)}",
    }
