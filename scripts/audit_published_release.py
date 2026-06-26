#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from ibex_agent_verification.evidence import EvidenceError, verify_manifest


_FORMAT = "ibex-agent-verification.release-asset-provenance.v1"
_TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PREFIX = PurePosixPath("cerebras-live-evidence")
_REQUIRED_ZIP_FILES = {
    "cerebras-live-evidence/bundle/manifest.json",
    "cerebras-live-evidence/bundle/analysis.json",
    "cerebras-live-evidence/bundle/raw/request.json",
    "cerebras-live-evidence/bundle/raw/capture.jsonl",
    "cerebras-live-evidence/verification.json",
    "cerebras-live-evidence/receipt.json",
    "cerebras-live-evidence/receipt.md",
}


class PublishedReleaseAuditError(ValueError):
    """Raised when a published release cannot be audited safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_asset_names(tag: str) -> dict[str, str]:
    if not _TAG_RE.fullmatch(tag):
        raise PublishedReleaseAuditError(f"invalid semantic release tag: {tag!r}")
    asset = f"{tag}-cerebras-live-evidence.zip"
    return {
        "asset": asset,
        "checksum": f"{asset}.sha256",
        "provenance": f"{asset}.provenance.json",
        "attestation": f"{tag}-release-attestation.sigstore.json",
    }


def _safe_member_name(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise PublishedReleaseAuditError(f"unsafe ZIP member name: {name!r}")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or str(path) != name
        or any(part in {"", ".", ".."} for part in path.parts)
        or not path.is_relative_to(_PREFIX)
    ):
        raise PublishedReleaseAuditError(f"unsafe ZIP member path: {name!r}")
    return path


def _extract_and_verify_bundle(asset: Path) -> dict[str, Any]:
    seen: set[str] = set()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with zipfile.ZipFile(asset) as archive:
            for member in archive.infolist():
                name = member.filename
                path = _safe_member_name(name)
                if name in seen:
                    raise PublishedReleaseAuditError(
                        f"duplicate ZIP member: {name}"
                    )
                seen.add(name)
                if member.is_dir():
                    raise PublishedReleaseAuditError(
                        f"release ZIP must contain files only: {name}"
                    )
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) != stat.S_IFREG or stat.S_IMODE(mode) != 0o644:
                    raise PublishedReleaseAuditError(
                        f"unexpected ZIP member mode for {name}: {oct(mode)}"
                    )
                if member.date_time != (1980, 1, 1, 0, 0, 0):
                    raise PublishedReleaseAuditError(
                        f"non-deterministic ZIP timestamp for {name}: {member.date_time}"
                    )
                if member.compress_type != zipfile.ZIP_DEFLATED:
                    raise PublishedReleaseAuditError(
                        f"unexpected ZIP compression for {name}: {member.compress_type}"
                    )
                target = root.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))

        missing = sorted(_REQUIRED_ZIP_FILES - seen)
        if missing:
            raise PublishedReleaseAuditError(
                f"release ZIP is missing required files: {missing}"
            )

        bundle = root / _PREFIX / "bundle"
        try:
            manifest_result = verify_manifest(
                evidence_dir=bundle,
                manifest_path=bundle / "manifest.json",
            )
        except (EvidenceError, OSError) as error:
            raise PublishedReleaseAuditError(
                f"embedded evidence manifest verification failed: {error}"
            ) from error
        if manifest_result["status"] != "VERIFIED":
            raise PublishedReleaseAuditError(
                f"embedded evidence manifest mismatch: {manifest_result}"
            )
        return {
            "member_count": len(seen),
            "required_files_present": True,
            "manifest": manifest_result,
        }


def audit_published_release(
    *,
    directory: Path,
    tag: str,
    repository: str,
    commit: str,
    workflow: str = ".github/workflows/release.yml",
) -> dict[str, Any]:
    directory = directory.resolve()
    if not directory.is_dir():
        raise PublishedReleaseAuditError(
            f"release directory is not a directory: {directory}"
        )
    if not _REPOSITORY_RE.fullmatch(repository):
        raise PublishedReleaseAuditError(f"invalid repository name: {repository!r}")
    if not _COMMIT_RE.fullmatch(commit):
        raise PublishedReleaseAuditError(
            f"commit must be a 40-character lowercase SHA: {commit!r}"
        )
    workflow_path = PurePosixPath(workflow)
    if workflow_path.is_absolute() or ".." in workflow_path.parts:
        raise PublishedReleaseAuditError(
            f"workflow must be a safe repository-relative path: {workflow!r}"
        )

    names = release_asset_names(tag)
    paths = {name: directory / filename for name, filename in names.items()}
    for label, path in paths.items():
        if not path.is_file():
            raise PublishedReleaseAuditError(
                f"missing published {label} file: {path.name}"
            )

    observed_files = {path.name for path in directory.iterdir() if path.is_file()}
    expected_files = set(names.values())
    unexpected = sorted(observed_files - expected_files)
    if unexpected:
        raise PublishedReleaseAuditError(
            f"unexpected files in release audit directory: {unexpected}"
        )

    asset = paths["asset"]
    digest = _sha256(asset)
    size_bytes = asset.stat().st_size
    expected_checksum = f"{digest}  {names['asset']}\n"
    checksum_text = paths["checksum"].read_text(encoding="utf-8")

    try:
        provenance = json.loads(paths["provenance"].read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublishedReleaseAuditError(
            f"invalid release provenance JSON: {error}"
        ) from error
    expected_provenance = {
        "format": _FORMAT,
        "release": {
            "commit": commit,
            "repository": repository,
            "tag": tag,
        },
        "subject": {
            "digest": {"sha256": digest},
            "name": names["asset"],
            "size_bytes": size_bytes,
        },
        "builder": {
            "workflow": workflow,
        },
    }

    try:
        attestation = json.loads(paths["attestation"].read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublishedReleaseAuditError(
            f"invalid Sigstore bundle JSON: {error}"
        ) from error

    checks = {
        "asset_sha256_valid": bool(re.fullmatch(r"[0-9a-f]{64}", digest)),
        "checksum_exact_match": checksum_text == expected_checksum,
        "provenance_exact_match": provenance == expected_provenance,
        "sigstore_bundle_non_empty_json": isinstance(attestation, (dict, list))
        and bool(attestation),
    }
    if not all(checks.values()):
        raise PublishedReleaseAuditError(
            "published release metadata mismatch: "
            + json.dumps(checks, sort_keys=True)
        )

    archive = _extract_and_verify_bundle(asset)
    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "release": {
            "repository": repository,
            "tag": tag,
            "commit": commit,
            "workflow": workflow,
        },
        "asset": {
            "name": names["asset"],
            "size_bytes": size_bytes,
            "sha256": digest,
        },
        "checks": checks,
        "archive": archive,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently audit downloaded GitHub Release evidence assets."
    )
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--workflow", default=".github/workflows/release.yml")
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = audit_published_release(
            directory=args.directory,
            tag=args.tag,
            repository=args.repository,
            commit=args.commit,
            workflow=args.workflow,
        )
    except (OSError, PublishedReleaseAuditError) as error:
        print(f"published release audit error: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
