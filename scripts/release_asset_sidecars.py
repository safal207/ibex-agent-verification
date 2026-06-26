#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


_FORMAT = "ibex-agent-verification.release-asset-provenance.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ReleaseAssetSidecarError(ValueError):
    """Raised when release asset sidecars cannot be produced or checked safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_inputs(
    *,
    asset: Path,
    subject_name: str,
    repository: str,
    commit: str,
    tag: str,
    workflow: str,
) -> Path:
    asset = asset.resolve()
    if not asset.is_file():
        raise ReleaseAssetSidecarError(f"release asset is not a file: {asset}")
    if not subject_name or Path(subject_name).name != subject_name or subject_name in {".", ".."}:
        raise ReleaseAssetSidecarError(f"subject name must be a plain file name: {subject_name!r}")
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ReleaseAssetSidecarError(f"invalid repository name: {repository!r}")
    if not _COMMIT_RE.fullmatch(commit):
        raise ReleaseAssetSidecarError(f"commit must be a 40-character lowercase SHA: {commit!r}")
    if not _TAG_RE.fullmatch(tag):
        raise ReleaseAssetSidecarError(f"invalid semantic release tag: {tag!r}")
    workflow_path = Path(workflow)
    if workflow_path.is_absolute() or not workflow_path.parts or ".." in workflow_path.parts:
        raise ReleaseAssetSidecarError(f"workflow must be a safe repository-relative path: {workflow!r}")
    return asset


def _expected_provenance(
    *,
    subject_name: str,
    size_bytes: int,
    sha256: str,
    repository: str,
    commit: str,
    tag: str,
    workflow: str,
) -> dict[str, Any]:
    return {
        "format": _FORMAT,
        "release": {
            "commit": commit,
            "repository": repository,
            "tag": tag,
        },
        "subject": {
            "digest": {"sha256": sha256},
            "name": subject_name,
            "size_bytes": size_bytes,
        },
        "builder": {
            "workflow": workflow,
        },
    }


def write_release_asset_sidecars(
    *,
    asset: Path,
    subject_name: str,
    checksum: Path,
    provenance: Path,
    repository: str,
    commit: str,
    tag: str,
    workflow: str,
) -> dict[str, Any]:
    asset = _validate_inputs(
        asset=asset,
        subject_name=subject_name,
        repository=repository,
        commit=commit,
        tag=tag,
        workflow=workflow,
    )
    checksum = checksum.resolve()
    provenance = provenance.resolve()
    if len({asset, checksum, provenance}) != 3:
        raise ReleaseAssetSidecarError("asset, checksum, and provenance paths must be distinct")

    digest = _sha256(asset)
    size_bytes = asset.stat().st_size
    record = _expected_provenance(
        subject_name=subject_name,
        size_bytes=size_bytes,
        sha256=digest,
        repository=repository,
        commit=commit,
        tag=tag,
        workflow=workflow,
    )

    checksum.parent.mkdir(parents=True, exist_ok=True)
    provenance.parent.mkdir(parents=True, exist_ok=True)
    checksum.write_text(f"{digest}  {subject_name}\n", encoding="utf-8", newline="\n")
    provenance.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


def verify_release_asset_sidecars(
    *,
    asset: Path,
    subject_name: str,
    checksum: Path,
    provenance: Path,
    repository: str,
    commit: str,
    tag: str,
    workflow: str,
) -> dict[str, Any]:
    asset = _validate_inputs(
        asset=asset,
        subject_name=subject_name,
        repository=repository,
        commit=commit,
        tag=tag,
        workflow=workflow,
    )
    checksum = checksum.resolve()
    provenance = provenance.resolve()
    for label, path in (("checksum", checksum), ("provenance", provenance)):
        if not path.is_file():
            raise ReleaseAssetSidecarError(f"{label} sidecar is not a file: {path}")

    digest = _sha256(asset)
    size_bytes = asset.stat().st_size
    expected_checksum = f"{digest}  {subject_name}\n"
    expected_provenance = _expected_provenance(
        subject_name=subject_name,
        size_bytes=size_bytes,
        sha256=digest,
        repository=repository,
        commit=commit,
        tag=tag,
        workflow=workflow,
    )

    checksum_text = checksum.read_text(encoding="utf-8")
    provenance_error: str | None = None
    try:
        observed_provenance = json.loads(provenance.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        observed_provenance = None
        provenance_error = str(error)

    checks = {
        "checksum_exact_match": checksum_text == expected_checksum,
        "provenance_exact_match": observed_provenance == expected_provenance,
        "subject_sha256_valid": bool(_SHA256_RE.fullmatch(digest)),
    }
    verified = all(checks.values())
    return {
        "schema_version": 1,
        "status": "VERIFIED" if verified else "METADATA_MISMATCH",
        "checks": checks,
        "subject": {
            "name": subject_name,
            "size_bytes": size_bytes,
            "sha256": digest,
        },
        "checksum": {
            "path": str(checksum),
            "expected": expected_checksum.rstrip("\n"),
            "observed": checksum_text.rstrip("\n"),
        },
        "provenance": {
            "path": str(provenance),
            "parse_error": provenance_error,
        },
    }


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--asset", required=True, type=Path)
    parser.add_argument("--subject-name", required=True)
    parser.add_argument("--checksum", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--workflow", required=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write or verify deterministic SHA-256 and provenance sidecars for a release asset."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    write_parser = subparsers.add_parser("write")
    _add_common_arguments(write_parser)

    verify_parser = subparsers.add_parser("verify")
    _add_common_arguments(verify_parser)
    verify_parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    common = {
        "asset": args.asset,
        "subject_name": args.subject_name,
        "checksum": args.checksum,
        "provenance": args.provenance,
        "repository": args.repository,
        "commit": args.commit,
        "tag": args.tag,
        "workflow": args.workflow,
    }
    try:
        if args.command == "write":
            result = write_release_asset_sidecars(**common)
            rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
            print(rendered, end="")
            return 0

        result = verify_release_asset_sidecars(**common)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered, encoding="utf-8", newline="\n")
        print(rendered, end="")
        return 0 if result["status"] == "VERIFIED" else 1
    except (OSError, ReleaseAssetSidecarError) as error:
        print(f"release asset sidecar error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
