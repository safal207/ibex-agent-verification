#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    from scripts import proofqa_gate_v3 as json_support
except ImportError:  # Direct execution from scripts directory.
    import proofqa_gate_v3 as json_support


class TrustedTransitionReferenceError(ValueError):
    """Raised when trusted reference assembly or audit is unsafe."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TrustedTransitionReferenceError(
            f"{label} must be a regular non-symlink file: {path}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TrustedTransitionReferenceError(
            f"{path}: invalid {label} JSON: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise TrustedTransitionReferenceError(f"{label} must be a JSON object")
    return value


def _safe_directory(path: Path, *, label: str, must_exist: bool) -> Path:
    if path.is_symlink():
        raise TrustedTransitionReferenceError(f"{label} must not be a symlink: {path}")
    resolved = path.resolve(strict=must_exist)
    if must_exist and not resolved.is_dir():
        raise TrustedTransitionReferenceError(f"{label} is not a directory: {path}")
    return resolved


def assemble_reference(
    *,
    source_dir: Path,
    output_dir: Path,
    repository: str,
    source_commit: str,
    trigger_run_id: int,
    trigger_workflow: str,
) -> dict[str, Any]:
    source = _safe_directory(source_dir, label="source directory", must_exist=True)
    output = _safe_directory(output_dir, label="output directory", must_exist=False)
    if output.exists():
        raise TrustedTransitionReferenceError(
            f"output directory must not already exist: {output_dir}"
        )
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise TrustedTransitionReferenceError(
            "source and output directories must not contain each other"
        )
    if not repository or "/" not in repository or len(repository) > 200:
        raise TrustedTransitionReferenceError("repository must use owner/name form")
    if len(source_commit) != 40 or any(ch not in "0123456789abcdef" for ch in source_commit):
        raise TrustedTransitionReferenceError(
            "source commit must be 40 lowercase hexadecimal characters"
        )
    if isinstance(trigger_run_id, bool) or trigger_run_id <= 0:
        raise TrustedTransitionReferenceError("trigger run id must be a positive integer")
    if trigger_workflow != "ProofQA Release Gate Action":
        raise TrustedTransitionReferenceError(
            "trusted producer requires ProofQA Release Gate Action as trigger"
        )

    required = [
        source / "transition-report.json",
        source / "evidence/action.json",
        source / "evidence/intent.json",
        source / "evidence/result.json",
        source / "evidence/verification.json",
    ]
    for path in required:
        if path.is_symlink() or not path.is_file():
            raise TrustedTransitionReferenceError(
                f"required reference source file is missing or unsafe: {path}"
            )

    (output / "evidence").mkdir(parents=True)
    shutil.copyfile(source / "transition-report.json", output / "transition-report.json")
    for name in ("action.json", "intent.json", "result.json", "verification.json"):
        shutil.copyfile(source / "evidence" / name, output / "evidence" / name)

    provenance = {
        "claim_boundary": (
            "This signed reference bundle verifies the trusted post-CI producer path. "
            "It is not a production deployment claim."
        ),
        "kind": "trusted-transition-reference",
        "producer_workflow": ".github/workflows/trusted-transition-manifest.yml",
        "repository": repository,
        "schema_version": 1,
        "source_commit": source_commit,
        "trigger": {
            "branch": "main",
            "event": "push",
            "run_id": trigger_run_id,
            "workflow": trigger_workflow,
        },
    }
    provenance_path = output / "producer-provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "schema_version": 1,
        "status": "ASSEMBLED",
        "output_dir": str(output),
        "source_commit": source_commit,
        "files": 6,
        "provenance_sha256": sha256_file(provenance_path),
    }


def audit_reference(
    *,
    root_dir: Path,
    expected_repository: str,
    expected_commit: str,
) -> dict[str, Any]:
    root = _safe_directory(root_dir, label="trusted reference root", must_exist=True)
    bundle = root / "bundle"
    manifest_path = bundle / "manifest.json"
    receipt_path = root / "manifest-receipt.json"
    report_path = root / "proofqa-gate-report.json"
    provenance_path = bundle / "producer-provenance.json"
    sigstore_path = root / "manifest.sigstore.json"

    manifest = _load_json(manifest_path, label="transition manifest")
    receipt = _load_json(receipt_path, label="manifest receipt")
    report = _load_json(report_path, label="ProofQA gate report")
    provenance = _load_json(provenance_path, label="producer provenance")
    _load_json(sigstore_path, label="Sigstore bundle")

    if provenance.get("repository") != expected_repository:
        raise TrustedTransitionReferenceError("provenance repository mismatch")
    if provenance.get("source_commit") != expected_commit:
        raise TrustedTransitionReferenceError("provenance source commit mismatch")
    if provenance.get("kind") != "trusted-transition-reference":
        raise TrustedTransitionReferenceError("unexpected provenance kind")
    if "not a production deployment claim" not in str(provenance.get("claim_boundary")):
        raise TrustedTransitionReferenceError("reference claim boundary is missing")

    expected_paths = {
        "evidence/action.json",
        "evidence/intent.json",
        "evidence/result.json",
        "evidence/verification.json",
        "producer-provenance.json",
        "transition-report.json",
    }
    files = manifest.get("files")
    if not isinstance(files, list):
        raise TrustedTransitionReferenceError("manifest files must be an array")
    paths = {
        item.get("path")
        for item in files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if paths != expected_paths or len(files) != len(expected_paths):
        raise TrustedTransitionReferenceError("manifest inventory is not the exact reference set")

    attestation = receipt.get("attestation")
    if not isinstance(attestation, dict) or attestation.get("status") != "VERIFIED":
        raise TrustedTransitionReferenceError("manifest attestation is not VERIFIED")
    if attestation.get("repository") != expected_repository:
        raise TrustedTransitionReferenceError("attestation repository mismatch")
    expected_signer = (
        f"{expected_repository}/.github/workflows/trusted-transition-manifest.yml"
    )
    if attestation.get("signer_workflow") != expected_signer:
        raise TrustedTransitionReferenceError("attestation signer workflow mismatch")
    if attestation.get("deny_self_hosted_runners") is not True:
        raise TrustedTransitionReferenceError("self-hosted runners were not denied")

    if report.get("schema_version") != 4 or report.get("decision") != "PASS":
        raise TrustedTransitionReferenceError("final ProofQA report is not schema v4 PASS")
    transition_manifest = report.get("transition_manifest")
    if not isinstance(transition_manifest, dict):
        raise TrustedTransitionReferenceError("ProofQA report lacks transition manifest")
    report_attestation = transition_manifest.get("attestation")
    if not isinstance(report_attestation, dict) or report_attestation.get("status") != "VERIFIED":
        raise TrustedTransitionReferenceError(
            "ProofQA report does not preserve VERIFIED attestation"
        )
    manifest_sha = sha256_file(manifest_path)
    source = report.get("source")
    if not isinstance(source, dict) or source.get("transition_manifest_sha256") != manifest_sha:
        raise TrustedTransitionReferenceError("ProofQA manifest digest mismatch")

    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "repository": expected_repository,
        "source_commit": expected_commit,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": sha256_file(receipt_path),
        "gate_report_sha256": sha256_file(report_path),
        "sigstore_bundle_sha256": sha256_file(sigstore_path),
        "files_checked": len(files),
        "claim_boundary": provenance["claim_boundary"],
    }


def _write_report(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    if path.is_symlink() or path.is_dir():
        raise TrustedTransitionReferenceError(
            f"report must be a writable regular-file path: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble or audit a trusted ProofQA transition reference"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--source-dir", type=Path, required=True)
    assemble.add_argument("--output-dir", type=Path, required=True)
    assemble.add_argument("--repository", required=True)
    assemble.add_argument("--source-commit", required=True)
    assemble.add_argument("--trigger-run-id", type=int, required=True)
    assemble.add_argument("--trigger-workflow", required=True)
    assemble.add_argument("--report", type=Path)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--root-dir", type=Path, required=True)
    audit.add_argument("--expected-repository", required=True)
    audit.add_argument("--expected-commit", required=True)
    audit.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "assemble":
            result = assemble_reference(
                source_dir=args.source_dir,
                output_dir=args.output_dir,
                repository=args.repository,
                source_commit=args.source_commit,
                trigger_run_id=args.trigger_run_id,
                trigger_workflow=args.trigger_workflow,
            )
        else:
            result = audit_reference(
                root_dir=args.root_dir,
                expected_repository=args.expected_repository,
                expected_commit=args.expected_commit,
            )
        _write_report(args.report, result)
    except (OSError, TrustedTransitionReferenceError, ValueError) as error:
        message = json_support._escape_workflow_command(str(error))
        print(f"::error title=Trusted transition reference error::{message}")
        print(f"Trusted transition reference error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
