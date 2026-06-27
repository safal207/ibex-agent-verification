#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts import proofqa_gate_v3 as json_support
    from scripts.proofqa_transition_preflight import validate_transition_evidence
except ImportError:  # Direct execution from the scripts directory.
    import proofqa_gate_v3 as json_support
    from proofqa_transition_preflight import validate_transition_evidence


class TransitionManifestError(ValueError):
    """Raised when transition evidence cannot be bound to a safe manifest."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_REF_RE = re.compile(r"^manifest:(?P<path>[^#]+)$")
_EVIDENCE_ROLES = (
    "intent_ref",
    "action_ref",
    "result_ref",
    "verification_ref",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TransitionManifestError(
            f"{label} must be a regular non-symlink file: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TransitionManifestError(
            f"{path}: invalid {label} JSON: {error.msg}"
        ) from error
    except OSError as error:
        raise TransitionManifestError(f"cannot read {label} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise TransitionManifestError(f"{label} must be a JSON object")
    return payload


def _canonical_relative_path(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise TransitionManifestError(
            f"{label} must be a non-empty canonical POSIX relative path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise TransitionManifestError(
            f"{label} must be a canonical POSIX relative path: {value!r}"
        )
    return path


def _non_negative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TransitionManifestError(f"{label} must be a non-negative integer")
    return value


def _manifest_inventory(
    *,
    evidence_dir: Path,
    manifest_path: Path,
) -> tuple[Path, Path, dict[str, dict[str, Any]]]:
    try:
        root = evidence_dir.resolve(strict=True)
    except OSError as error:
        raise TransitionManifestError(
            f"transition evidence directory does not exist: {evidence_dir}"
        ) from error
    if not root.is_dir():
        raise TransitionManifestError(
            f"transition evidence directory is not a directory: {evidence_dir}"
        )

    if manifest_path.is_symlink():
        raise TransitionManifestError(
            f"transition manifest must not be a symlink: {manifest_path}"
        )
    try:
        manifest = manifest_path.resolve(strict=True)
    except OSError as error:
        raise TransitionManifestError(
            f"transition manifest does not exist: {manifest_path}"
        ) from error
    if not manifest.is_file() or not manifest.is_relative_to(root):
        raise TransitionManifestError(
            "transition manifest must be a regular file inside the evidence directory"
        )

    payload = _load_json(manifest, label="transition evidence manifest")
    if payload.get("schema_version") != 1:
        raise TransitionManifestError("transition manifest schema_version must equal 1")
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise TransitionManifestError("transition manifest files must be a non-empty array")

    inventory: dict[str, dict[str, Any]] = {}
    mismatches: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "size_bytes",
            "sha256",
        }:
            raise TransitionManifestError(
                f"manifest files[{index}] must contain exactly path, size_bytes, and sha256"
            )
        relative = _canonical_relative_path(
            entry["path"],
            label=f"manifest files[{index}].path",
        )
        relative_text = relative.as_posix()
        if relative_text in inventory:
            raise TransitionManifestError(
                f"transition manifest contains duplicate path: {relative_text}"
            )
        expected_size = _non_negative_int(
            entry["size_bytes"],
            label=f"manifest files[{index}].size_bytes",
        )
        expected_sha = entry["sha256"]
        if not isinstance(expected_sha, str) or not _SHA256_RE.fullmatch(expected_sha):
            raise TransitionManifestError(
                f"manifest files[{index}].sha256 must be 64 lowercase hexadecimal characters"
            )

        candidate = root.joinpath(*relative.parts)
        if candidate == manifest:
            raise TransitionManifestError("transition manifest cannot list itself")
        if not candidate.exists():
            mismatches.append(f"{relative_text}:MISSING")
            inventory[relative_text] = {
                "path": relative_text,
                "size_bytes": expected_size,
                "sha256": expected_sha,
            }
            continue
        if candidate.is_symlink() or not candidate.is_file():
            raise TransitionManifestError(
                f"manifest path is not a regular file: {relative_text}"
            )
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise TransitionManifestError(
                f"manifest path escapes evidence directory: {relative_text}"
            )
        actual_size = candidate.stat().st_size
        actual_sha = sha256_file(candidate)
        if actual_size != expected_size:
            mismatches.append(
                f"{relative_text}:SIZE_MISMATCH:{expected_size}:{actual_size}"
            )
        if actual_sha != expected_sha:
            mismatches.append(
                f"{relative_text}:SHA256_MISMATCH:{expected_sha}:{actual_sha}"
            )
        inventory[relative_text] = {
            "path": relative_text,
            "size_bytes": expected_size,
            "sha256": expected_sha,
        }

    actual_files: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise TransitionManifestError(
                "transition evidence bundle contains a symlink: "
                f"{candidate.relative_to(root).as_posix()}"
            )
        if candidate.is_file() and candidate.resolve() != manifest:
            actual_files.add(candidate.relative_to(root).as_posix())
    unlisted = sorted(actual_files - set(inventory))
    mismatches.extend(f"{path}:UNLISTED" for path in unlisted)
    if mismatches:
        raise TransitionManifestError(
            "transition evidence manifest integrity mismatch: " + "; ".join(mismatches)
        )
    return root, manifest, inventory


def _manifest_reference(value: str, *, role: str) -> str:
    match = _MANIFEST_REF_RE.fullmatch(value)
    if match is None:
        raise TransitionManifestError(
            f"transition.evidence.{role} must use manifest:<canonical-relative-path>"
        )
    return _canonical_relative_path(
        match.group("path"),
        label=f"transition.evidence.{role}",
    ).as_posix()


def verify_transition_manifest(
    *,
    evidence_dir: Path,
    manifest_path: Path,
    transition_report_path: Path,
    policy: str,
) -> dict[str, Any]:
    if policy not in {"verify", "require-attested"}:
        raise TransitionManifestError(
            "transition manifest policy must be verify or require-attested"
        )
    root, manifest, inventory = _manifest_inventory(
        evidence_dir=evidence_dir,
        manifest_path=manifest_path,
    )
    if transition_report_path.is_symlink():
        raise TransitionManifestError(
            f"transition report must not be a symlink: {transition_report_path}"
        )
    try:
        transition_report = transition_report_path.resolve(strict=True)
    except OSError as error:
        raise TransitionManifestError(
            f"transition report does not exist: {transition_report_path}"
        ) from error
    if not transition_report.is_file() or not transition_report.is_relative_to(root):
        raise TransitionManifestError(
            "transition report must be a regular file inside the evidence directory"
        )
    transition_relative = transition_report.relative_to(root).as_posix()
    transition_entry = inventory.get(transition_relative)
    if transition_entry is None:
        raise TransitionManifestError(
            "transition report itself must be listed in the transition manifest"
        )

    raw_transition = _load_json(
        transition_report,
        label="ProofQA transition report",
    )
    normalized = validate_transition_evidence(raw_transition)
    bound_refs: dict[str, dict[str, Any] | None] = {}
    observed_paths: set[str] = set()
    for role in _EVIDENCE_ROLES:
        value = normalized["evidence"][role]
        if value is None:
            bound_refs[role] = None
            continue
        relative = _manifest_reference(value, role=role)
        if relative == transition_relative:
            raise TransitionManifestError(
                f"transition.evidence.{role} cannot reference the transition report itself"
            )
        if relative in observed_paths:
            raise TransitionManifestError(
                "each non-null transition evidence role must reference a distinct manifest file"
            )
        observed_paths.add(relative)
        entry = inventory.get(relative)
        if entry is None:
            raise TransitionManifestError(
                f"transition.evidence.{role} references a file absent from the manifest: {relative}"
            )
        bound_refs[role] = dict(entry)

    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "policy": policy,
        "transition": {
            "transition_id": normalized["transition_id"],
            "status": normalized["status"],
            "phase": normalized["phase"],
            "report_path": transition_relative,
            "report_size_bytes": transition_entry["size_bytes"],
            "report_sha256": transition_entry["sha256"],
        },
        "manifest": {
            "path": manifest.relative_to(root).as_posix(),
            "sha256": sha256_file(manifest),
            "files_checked": len(inventory),
        },
        "references": bound_refs,
        "attestation": {
            "required": policy == "require-attested",
            "status": "PENDING" if policy == "require-attested" else "NOT_REQUIRED",
        },
        "claim_boundary": (
            "This receipt proves that the transition report and every non-null canonical "
            "manifest reference matched one exact local evidence inventory by path, size, and "
            "SHA-256. Attestation is proven only when attestation.status is VERIFIED."
        ),
    }


def _non_empty_json_file(path: Path, *, label: str) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise TransitionManifestError(
            f"{label} must be a non-empty regular non-symlink file: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TransitionManifestError(
            f"{path}: invalid {label} JSON: {error.msg}"
        ) from error
    if payload in ({}, [], None):
        raise TransitionManifestError(f"{label} JSON must not be empty")
    return sha256_file(path)


def finalize_attestation(
    *,
    receipt_path: Path,
    online_report_path: Path,
    bundled_report_path: Path,
    attestation_bundle_path: Path,
    repository: str,
    signer_workflow: str,
) -> dict[str, Any]:
    receipt = _load_json(receipt_path, label="transition manifest receipt")
    if receipt.get("status") != "VERIFIED" or receipt.get("policy") != "require-attested":
        raise TransitionManifestError(
            "attestation finalization requires a VERIFIED require-attested manifest receipt"
        )
    attestation = receipt.get("attestation")
    if not isinstance(attestation, dict) or attestation.get("status") != "PENDING":
        raise TransitionManifestError(
            "transition manifest receipt attestation must be PENDING before finalization"
        )
    if not repository or "/" not in repository or len(repository) > 200:
        raise TransitionManifestError("attestation repository must use owner/repository form")
    if (
        not signer_workflow
        or not signer_workflow.startswith(repository + "/.github/workflows/")
        or not signer_workflow.endswith((".yml", ".yaml"))
        or len(signer_workflow) > 300
    ):
        raise TransitionManifestError(
            "signer workflow must be an explicit workflow path inside the attestation repository"
        )
    if attestation_bundle_path.is_symlink() or not attestation_bundle_path.is_file():
        raise TransitionManifestError(
            f"attestation bundle must be a regular non-symlink file: {attestation_bundle_path}"
        )
    bundle_sha = _non_empty_json_file(
        attestation_bundle_path,
        label="Sigstore attestation bundle",
    )
    online_sha = _non_empty_json_file(
        online_report_path,
        label="online attestation verification report",
    )
    bundled_sha = _non_empty_json_file(
        bundled_report_path,
        label="bundled attestation verification report",
    )
    receipt["attestation"] = {
        "required": True,
        "status": "VERIFIED",
        "repository": repository,
        "signer_workflow": signer_workflow,
        "deny_self_hosted_runners": True,
        "bundle_path": str(attestation_bundle_path),
        "bundle_sha256": bundle_sha,
        "online_report_path": str(online_report_path),
        "online_report_sha256": online_sha,
        "bundled_report_path": str(bundled_report_path),
        "bundled_report_sha256": bundled_sha,
    }
    return receipt


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.is_symlink() or path.is_dir():
        raise TransitionManifestError(
            f"output must be a writable regular-file path: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind ProofQA transition evidence to an exact manifest inventory"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--evidence-dir", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--transition-report", type=Path, required=True)
    verify.add_argument(
        "--policy",
        choices=("verify", "require-attested"),
        required=True,
    )
    verify.add_argument("--receipt", type=Path, required=True)

    finalize = subparsers.add_parser("finalize-attestation")
    finalize.add_argument("--receipt", type=Path, required=True)
    finalize.add_argument("--online-report", type=Path, required=True)
    finalize.add_argument("--bundled-report", type=Path, required=True)
    finalize.add_argument("--attestation-bundle", type=Path, required=True)
    finalize.add_argument("--repository", required=True)
    finalize.add_argument("--signer-workflow", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            receipt = verify_transition_manifest(
                evidence_dir=args.evidence_dir,
                manifest_path=args.manifest,
                transition_report_path=args.transition_report,
                policy=args.policy,
            )
            _write_json(args.receipt, receipt)
        else:
            receipt = finalize_attestation(
                receipt_path=args.receipt,
                online_report_path=args.online_report,
                bundled_report_path=args.bundled_report,
                attestation_bundle_path=args.attestation_bundle,
                repository=args.repository,
                signer_workflow=args.signer_workflow,
            )
            _write_json(args.receipt, receipt)
    except (OSError, TransitionManifestError, ValueError) as error:
        message = json_support._escape_workflow_command(str(error))
        print(f"::error title=ProofQA transition manifest error::{message}")
        print(f"ProofQA transition manifest error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
