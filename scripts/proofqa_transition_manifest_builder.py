#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts import proofqa_gate_v3 as json_support
    from scripts.proofqa_transition_manifest import (
        TransitionManifestError,
        _manifest_reference,
        sha256_file,
        verify_transition_manifest,
    )
    from scripts.proofqa_transition_preflight import validate_transition_evidence
except ImportError:  # Direct execution from the scripts directory.
    import proofqa_gate_v3 as json_support
    from proofqa_transition_manifest import (
        TransitionManifestError,
        _manifest_reference,
        sha256_file,
        verify_transition_manifest,
    )
    from proofqa_transition_preflight import validate_transition_evidence


class TransitionManifestBuildError(ValueError):
    """Raised when a deterministic transition manifest cannot be built safely."""


def _resolve_root(evidence_dir: Path) -> Path:
    try:
        root = evidence_dir.resolve(strict=True)
    except OSError as error:
        raise TransitionManifestBuildError(
            f"transition evidence directory does not exist: {evidence_dir}"
        ) from error
    if not root.is_dir():
        raise TransitionManifestBuildError(
            f"transition evidence directory is not a directory: {evidence_dir}"
        )
    return root


def _resolve_output(root: Path, output: Path) -> Path:
    if output.is_symlink() or output.is_dir():
        raise TransitionManifestBuildError(
            f"manifest output must be a regular-file path: {output}"
        )
    resolved = output.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise TransitionManifestBuildError(
            "manifest output must be inside the transition evidence directory"
        )
    return resolved


def _collect_files(root: Path, output: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise TransitionManifestBuildError(
                "transition evidence source contains a symlink: "
                f"{candidate.relative_to(root).as_posix()}"
            )
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise TransitionManifestBuildError(
                "transition evidence source contains a non-regular path: "
                f"{candidate.relative_to(root).as_posix()}"
            )
        resolved = candidate.resolve(strict=True)
        if resolved == output:
            continue
        if not resolved.is_relative_to(root):
            raise TransitionManifestBuildError(
                "transition evidence source escapes its root: "
                f"{candidate.relative_to(root).as_posix()}"
            )
        entries.append(
            {
                "path": candidate.relative_to(root).as_posix(),
                "size_bytes": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
            }
        )
    if not entries:
        raise TransitionManifestBuildError(
            "transition evidence directory contains no files to inventory"
        )
    return entries


def _validate_transition_bindings(
    *,
    root: Path,
    entries: list[dict[str, Any]],
    transition_report_relative: str,
) -> dict[str, Any]:
    inventory = {entry["path"]: entry for entry in entries}
    transition_entry = inventory.get(transition_report_relative)
    if transition_entry is None:
        raise TransitionManifestBuildError(
            f"transition report is absent from source inventory: {transition_report_relative}"
        )
    transition_path = root / transition_report_relative
    try:
        payload = json.loads(transition_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TransitionManifestBuildError(
            f"{transition_path}: invalid transition JSON: {error.msg}"
        ) from error
    if not isinstance(payload, dict):
        raise TransitionManifestBuildError("transition report must be a JSON object")
    normalized = validate_transition_evidence(payload)

    bound_paths: set[str] = set()
    for role, value in normalized["evidence"].items():
        if value is None:
            continue
        relative = _manifest_reference(value, role=role)
        if relative == transition_report_relative:
            raise TransitionManifestBuildError(
                f"transition.evidence.{role} cannot reference the transition report itself"
            )
        if relative in bound_paths:
            raise TransitionManifestBuildError(
                "each non-null transition evidence role must reference a distinct file"
            )
        bound_paths.add(relative)
        if relative not in inventory:
            raise TransitionManifestBuildError(
                f"transition.evidence.{role} references a missing source file: {relative}"
            )
    return normalized


def build_transition_manifest(
    *,
    evidence_dir: Path,
    output: Path,
    transition_report_relative: str = "transition-report.json",
) -> dict[str, Any]:
    root = _resolve_root(evidence_dir)
    output_resolved = _resolve_output(root, output)
    transition_report_relative = Path(transition_report_relative).as_posix()
    if (
        not transition_report_relative
        or transition_report_relative.startswith("/")
        or "\\" in transition_report_relative
        or any(part in {"", ".", ".."} for part in Path(transition_report_relative).parts)
    ):
        raise TransitionManifestBuildError(
            "transition report path must be a canonical relative POSIX path"
        )

    entries = _collect_files(root, output_resolved)
    normalized = _validate_transition_bindings(
        root=root,
        entries=entries,
        transition_report_relative=transition_report_relative,
    )
    manifest = {
        "files": entries,
        "schema_version": 1,
    }
    output_resolved.parent.mkdir(parents=True, exist_ok=True)
    output_resolved.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    verification = verify_transition_manifest(
        evidence_dir=root,
        manifest_path=output_resolved,
        transition_report_path=root / transition_report_relative,
        policy="verify",
    )
    return {
        "schema_version": 1,
        "status": "MANIFEST_BUILT",
        "transition_id": normalized["transition_id"],
        "transition_status": normalized["status"],
        "transition_phase": normalized["phase"],
        "manifest_path": output_resolved.relative_to(root).as_posix(),
        "manifest_sha256": sha256_file(output_resolved),
        "files": len(entries),
        "verification_status": verification["status"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic ProofQA transition evidence manifest"
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--transition-report-relative",
        default="transition-report.json",
    )
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_transition_manifest(
            evidence_dir=args.evidence_dir,
            output=args.output,
            transition_report_relative=args.transition_report_relative,
        )
        if args.report is not None:
            if args.report.is_symlink() or args.report.is_dir():
                raise TransitionManifestBuildError(
                    f"build report must be a writable regular-file path: {args.report}"
                )
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    except (
        OSError,
        TransitionManifestBuildError,
        TransitionManifestError,
        ValueError,
    ) as error:
        message = json_support._escape_workflow_command(str(error))
        print(f"::error title=ProofQA transition manifest build error::{message}")
        print(f"ProofQA transition manifest build error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
