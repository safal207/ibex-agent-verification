#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


class TrustedTransitionArtifactError(ValueError):
    """Raised when cross-workflow transition artifact ingestion is unsafe."""


EXPECTED_SOURCE_FILES = {
    "source-provenance.json",
    "transition-report.json",
    "evidence/intent.json",
    "evidence/action.json",
    "evidence/result.json",
    "evidence/verification.json",
}
_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_WORKFLOW_RE = re.compile(r"^\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml$")
_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_FILE_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 32
_COPY_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrustedTransitionArtifactError(
                f"JSON object contains duplicate key: {key}"
            )
        result[key] = value
    return result


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TrustedTransitionArtifactError(
            f"{label} must be a regular non-symlink file: {path}"
        )
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except UnicodeDecodeError as error:
        raise TrustedTransitionArtifactError(f"{label} must be UTF-8: {path}") from error
    except json.JSONDecodeError as error:
        raise TrustedTransitionArtifactError(
            f"{path}: invalid {label} JSON: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise TrustedTransitionArtifactError(f"{label} must be a JSON object")
    return value


def write_json(
    path: Path,
    payload: dict[str, Any],
    *,
    forbidden_root: Path | None = None,
) -> None:
    if path.is_symlink() or path.is_dir():
        raise TrustedTransitionArtifactError(
            f"output must be a writable regular-file path: {path}"
        )
    resolved = path.resolve(strict=False)
    if (
        forbidden_root is not None
        and resolved.is_relative_to(forbidden_root.resolve(strict=True))
    ):
        raise TrustedTransitionArtifactError(
            "derived report must be written outside the verified source directory"
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TrustedTransitionArtifactError(f"{label} must be a positive integer")
    return value


def text(value: Any, *, label: str, maximum: int = 500) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "\n" in value
        or "\r" in value
    ):
        raise TrustedTransitionArtifactError(
            f"{label} must be a single-line non-empty string of at most {maximum} characters"
        )
    return value.strip()


def repository(value: Any, *, label: str) -> str:
    normalized = text(value, label=label, maximum=201)
    if not _REPOSITORY_RE.fullmatch(normalized):
        raise TrustedTransitionArtifactError(
            f"{label} must use canonical owner/repository form"
        )
    return normalized


def commit(value: Any, *, label: str) -> str:
    normalized = text(value, label=label, maximum=40)
    if not _COMMIT_RE.fullmatch(normalized):
        raise TrustedTransitionArtifactError(
            f"{label} must be 40 lowercase hexadecimal characters"
        )
    return normalized


def digest(value: Any, *, label: str) -> str:
    normalized = text(value, label=label, maximum=71)
    if not _DIGEST_RE.fullmatch(normalized):
        raise TrustedTransitionArtifactError(
            f"{label} must use lowercase sha256:<64-hex> form"
        )
    return normalized


def artifact_name(value: Any, *, label: str) -> str:
    normalized = text(value, label=label, maximum=255)
    if not _NAME_RE.fullmatch(normalized) or ".." in PurePosixPath(normalized).parts:
        raise TrustedTransitionArtifactError(f"{label} is not canonical")
    return normalized


def workflow(value: Any, *, label: str) -> str:
    normalized = text(value, label=label, maximum=300)
    path = PurePosixPath(normalized)
    if (
        not _WORKFLOW_RE.fullmatch(normalized)
        or "\\" in normalized
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != normalized
    ):
        raise TrustedTransitionArtifactError(
            f"{label} must identify one canonical .github/workflows/*.yml or *.yaml file"
        )
    return normalized


def select_artifact(
    *,
    api_payload: dict[str, Any],
    expected_repository: str,
    expected_repository_id: int,
    expected_head_repository_id: int,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_workflow: str,
    expected_head_branch: str,
    expected_head_sha: str,
    expected_name: str,
) -> dict[str, Any]:
    repo = repository(expected_repository, label="expected repository")
    repo_id = positive_int(expected_repository_id, label="expected repository id")
    head_repo_id = positive_int(
        expected_head_repository_id, label="expected head repository id"
    )
    run_id = positive_int(expected_run_id, label="expected run id")
    run_attempt = positive_int(expected_run_attempt, label="expected run attempt")
    workflow_path = workflow(expected_workflow, label="expected workflow")
    head_branch = text(expected_head_branch, label="expected head branch", maximum=200)
    head_sha = commit(expected_head_sha, label="expected head SHA")
    name = artifact_name(expected_name, label="expected artifact name")

    total_count = api_payload.get("total_count")
    artifacts = api_payload.get("artifacts")
    if isinstance(total_count, bool) or not isinstance(total_count, int):
        raise TrustedTransitionArtifactError("artifact API total_count must be an integer")
    if not isinstance(artifacts, list):
        raise TrustedTransitionArtifactError("artifact API artifacts must be an array")
    if total_count != 1 or len(artifacts) != 1:
        raise TrustedTransitionArtifactError(
            f"expected exactly one artifact named {name!r}; "
            f"total_count={total_count}, returned={len(artifacts)}"
        )
    artifact = artifacts[0]
    if not isinstance(artifact, dict):
        raise TrustedTransitionArtifactError("artifact API entry must be an object")
    artifact_id = positive_int(artifact.get("id"), label="artifact id")
    selected_name = artifact_name(artifact.get("name"), label="artifact name")
    if selected_name != name:
        raise TrustedTransitionArtifactError("artifact name mismatch")
    if artifact.get("expired") is not False:
        raise TrustedTransitionArtifactError("artifact must exist and not be expired")
    size_bytes = positive_int(artifact.get("size_in_bytes"), label="artifact size")
    if size_bytes > _MAX_ARCHIVE_BYTES:
        raise TrustedTransitionArtifactError("artifact exceeds the ingestion size limit")
    artifact_digest = digest(artifact.get("digest"), label="artifact digest")
    api_prefix = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}"
    if artifact.get("url") != api_prefix:
        raise TrustedTransitionArtifactError("artifact API URL mismatch")
    if artifact.get("archive_download_url") != f"{api_prefix}/zip":
        raise TrustedTransitionArtifactError("artifact archive URL mismatch")

    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict):
        raise TrustedTransitionArtifactError("artifact workflow_run must be an object")
    expected_run = {
        "id": run_id,
        "repository_id": repo_id,
        "head_repository_id": head_repo_id,
        "head_branch": head_branch,
        "head_sha": head_sha,
    }
    for key, expected in expected_run.items():
        if workflow_run.get(key) != expected:
            raise TrustedTransitionArtifactError(
                f"artifact workflow_run.{key} mismatch: "
                f"expected {expected!r}, got {workflow_run.get(key)!r}"
            )

    return {
        "schema_version": 1,
        "kind": "trusted-transition-artifact-selection",
        "status": "SELECTED",
        "repository": repo,
        "repository_id": repo_id,
        "head_repository_id": head_repo_id,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "workflow": workflow_path,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "artifact": {
            "id": artifact_id,
            "name": selected_name,
            "size_bytes": size_bytes,
            "digest": artifact_digest,
            "url": api_prefix,
            "archive_download_url": f"{api_prefix}/zip",
        },
    }


def append_github_outputs(path: Path, selection: dict[str, Any]) -> None:
    if path.is_symlink() or path.is_dir():
        raise TrustedTransitionArtifactError(f"GitHub output path is unsafe: {path}")
    artifact = selection["artifact"]
    values = {
        "artifact-id": str(artifact["id"]),
        "artifact-name": artifact["name"],
        "artifact-digest": artifact["digest"],
    }
    if any("\n" in value or "\r" in value for value in values.values()):
        raise TrustedTransitionArtifactError("GitHub output contains a line break")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _canonical_zip_name(info: zipfile.ZipInfo) -> tuple[str, bool]:
    name = info.filename
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise TrustedTransitionArtifactError(f"archive contains unsafe path: {name!r}")
    if unicodedata.normalize("NFC", name) != name:
        raise TrustedTransitionArtifactError(
            f"archive path is not NFC-normalized: {name!r}"
        )
    path = PurePosixPath(name)
    if (
        any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != name.rstrip("/")
    ):
        raise TrustedTransitionArtifactError(
            f"archive path is not canonical: {name!r}"
        )
    if path.parts and ":" in path.parts[0]:
        raise TrustedTransitionArtifactError(
            f"archive contains drive-like path: {name!r}"
        )
    return path.as_posix(), info.is_dir() or name.endswith("/")


def _validate_zip_mode(info: zipfile.ZipInfo, *, is_directory: bool) -> None:
    if info.flag_bits & 0x1:
        raise TrustedTransitionArtifactError(
            f"archive member is encrypted: {info.filename}"
        )
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise TrustedTransitionArtifactError(
            f"archive member uses unsupported compression: {info.filename}"
        )
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode):
        raise TrustedTransitionArtifactError(
            f"archive contains a symbolic link: {info.filename}"
        )
    allowed_kind = stat.S_IFDIR if is_directory else stat.S_IFREG
    if kind not in {0, allowed_kind}:
        raise TrustedTransitionArtifactError(
            f"archive contains a non-regular member: {info.filename}"
        )


def _copy_limited(
    source: BinaryIO,
    target: BinaryIO,
    *,
    limit: int,
    label: str,
) -> int:
    total = 0
    while True:
        chunk = source.read(min(_COPY_CHUNK, limit - total + 1))
        if not chunk:
            return total
        total += len(chunk)
        if total > limit:
            raise TrustedTransitionArtifactError(f"{label} exceeds {limit} bytes")
        target.write(chunk)


def extract_artifact(
    *,
    download_dir: Path,
    selection: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    if selection.get("schema_version") != 1 or selection.get("status") != "SELECTED":
        raise TrustedTransitionArtifactError(
            "artifact selection must be schema v1 SELECTED"
        )
    artifact = selection.get("artifact")
    if not isinstance(artifact, dict):
        raise TrustedTransitionArtifactError(
            "artifact selection lacks artifact metadata"
        )
    expected_digest = digest(
        artifact.get("digest"), label="selected artifact digest"
    )

    if download_dir.is_symlink():
        raise TrustedTransitionArtifactError(
            "download directory must not be a symlink"
        )
    root = download_dir.resolve(strict=True)
    if not root.is_dir():
        raise TrustedTransitionArtifactError("download path must be a directory")
    entries = list(root.iterdir())
    if len(entries) != 1:
        raise TrustedTransitionArtifactError(
            "download directory must contain exactly one archive file, "
            f"found {len(entries)}"
        )
    archive = entries[0]
    if archive.is_symlink() or not archive.is_file():
        raise TrustedTransitionArtifactError(
            "downloaded artifact must be one regular file"
        )
    archive_size = archive.stat().st_size
    if archive_size <= 0 or archive_size > _MAX_ARCHIVE_BYTES:
        raise TrustedTransitionArtifactError(
            "downloaded artifact archive size is unsafe"
        )
    actual_digest = f"sha256:{sha256_file(archive)}"
    if actual_digest != expected_digest:
        raise TrustedTransitionArtifactError(
            "downloaded artifact digest mismatch: "
            f"expected {expected_digest}, got {actual_digest}"
        )

    if output_dir.is_symlink() or output_dir.exists():
        raise TrustedTransitionArtifactError(
            f"extraction output directory must not already exist: {output_dir}"
        )
    output = output_dir.resolve(strict=False)
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise TrustedTransitionArtifactError(
            "download and extraction directories must not contain each other"
        )
    output.mkdir(parents=True, exist_ok=False)

    extracted: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(archive, "r") as zipped:
            infos = zipped.infolist()
            if not infos or len(infos) > _MAX_ENTRIES:
                raise TrustedTransitionArtifactError(
                    f"archive must contain between 1 and {_MAX_ENTRIES} entries"
                )
            seen: set[str] = set()
            folded: set[str] = set()
            files: set[str] = set()
            total_uncompressed = 0
            validated: list[tuple[zipfile.ZipInfo, str, bool]] = []
            for info in infos:
                name, is_directory = _canonical_zip_name(info)
                key = name.casefold()
                if name in seen or key in folded:
                    raise TrustedTransitionArtifactError(
                        "archive contains a duplicate or case-colliding path: "
                        f"{name}"
                    )
                seen.add(name)
                folded.add(key)
                _validate_zip_mode(info, is_directory=is_directory)
                if is_directory:
                    if name != "evidence":
                        raise TrustedTransitionArtifactError(
                            "archive contains an unexpected directory entry: "
                            f"{name}"
                        )
                else:
                    files.add(name)
                    if info.file_size < 0 or info.file_size > _MAX_FILE_BYTES:
                        raise TrustedTransitionArtifactError(
                            f"archive member size is unsafe: {name}"
                        )
                    total_uncompressed += info.file_size
                    if total_uncompressed > _MAX_TOTAL_BYTES:
                        raise TrustedTransitionArtifactError(
                            "archive total uncompressed size exceeds the limit"
                        )
                validated.append((info, name, is_directory))
            if files != EXPECTED_SOURCE_FILES:
                raise TrustedTransitionArtifactError(
                    "archive source layout mismatch; "
                    f"missing={sorted(EXPECTED_SOURCE_FILES - files)}, "
                    f"unexpected={sorted(files - EXPECTED_SOURCE_FILES)}"
                )

            for info, name, is_directory in validated:
                destination = output / name
                if not destination.resolve(strict=False).is_relative_to(output):
                    raise TrustedTransitionArtifactError(
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
                    raise TrustedTransitionArtifactError(
                        f"archive member size changed during extraction: {name}"
                    )
                extracted.append(
                    {
                        "path": name,
                        "size_bytes": written,
                        "sha256": sha256_file(destination),
                    }
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise TrustedTransitionArtifactError(
            f"unable to safely extract artifact archive: {error}"
        ) from error

    extracted.sort(key=lambda item: item["path"])
    return {
        "schema_version": 1,
        "kind": "trusted-transition-artifact-extraction",
        "status": "EXTRACTED",
        "repository": selection.get("repository"),
        "source_commit": selection.get("head_sha"),
        "run_id": selection.get("run_id"),
        "run_attempt": selection.get("run_attempt"),
        "artifact": artifact,
        "archive": {
            "filename": archive.name,
            "size_bytes": archive_size,
            "digest": actual_digest,
        },
        "files_checked": len(extracted),
        "files": extracted,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select and safely extract one trusted transition artifact"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select")
    select.add_argument("--api-json", type=Path, required=True)
    select.add_argument("--expected-repository", required=True)
    select.add_argument("--expected-repository-id", type=int, required=True)
    select.add_argument("--expected-head-repository-id", type=int, required=True)
    select.add_argument("--expected-run-id", type=int, required=True)
    select.add_argument("--expected-run-attempt", type=int, required=True)
    select.add_argument("--expected-workflow", required=True)
    select.add_argument("--expected-head-branch", required=True)
    select.add_argument("--expected-head-sha", required=True)
    select.add_argument("--expected-name", required=True)
    select.add_argument("--report", type=Path, required=True)
    select.add_argument("--github-output", type=Path)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--download-dir", type=Path, required=True)
    extract.add_argument("--selection", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)
    extract.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "select":
            result = select_artifact(
                api_payload=load_json_object(
                    args.api_json,
                    label="artifact API response",
                ),
                expected_repository=args.expected_repository,
                expected_repository_id=args.expected_repository_id,
                expected_head_repository_id=args.expected_head_repository_id,
                expected_run_id=args.expected_run_id,
                expected_run_attempt=args.expected_run_attempt,
                expected_workflow=args.expected_workflow,
                expected_head_branch=args.expected_head_branch,
                expected_head_sha=args.expected_head_sha,
                expected_name=args.expected_name,
            )
            write_json(args.report, result)
            if args.github_output is not None:
                append_github_outputs(args.github_output, result)
        else:
            selection = load_json_object(
                args.selection,
                label="artifact selection",
            )
            result = extract_artifact(
                download_dir=args.download_dir,
                selection=selection,
                output_dir=args.output_dir,
            )
            write_json(
                args.report,
                result,
                forbidden_root=args.output_dir,
            )
    except (OSError, TrustedTransitionArtifactError, ValueError) as error:
        print(f"trusted transition artifact error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
