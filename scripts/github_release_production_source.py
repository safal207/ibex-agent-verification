#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.production_transition_source import (
        ProductionTransitionSourceError,
        validate_production_transition_source,
    )
    from scripts.trusted_transition_artifact import (
        TrustedTransitionArtifactError,
        artifact_name,
        commit,
        digest,
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
    from production_transition_source import (
        ProductionTransitionSourceError,
        validate_production_transition_source,
    )
    from trusted_transition_artifact import (
        TrustedTransitionArtifactError,
        artifact_name,
        commit,
        digest,
        extract_artifact,
        load_json_object,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
        write_json,
    )


class GitHubReleaseProductionError(ValueError):
    """Raised when a GitHub Release deployment observation is unsafe."""


_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_CLAIM_BOUNDARY = (
    "This verified transition proves that the exact main-branch transition-source "
    "archive was published as one public, customer-consumable GitHub Release asset "
    "and re-downloaded from the live release service with identical SHA-256 bytes. "
    "It does not prove that a customer installed or executed the asset, physical "
    "hardware behavior, application correctness, or independent human approval, "
    "and it is not a physical production execution claim."
)


def _require_equal(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise GitHubReleaseProductionError(
            f"{label} mismatch: expected {expected!r}, got {actual!r}"
        )


def _tag(value: Any, *, label: str) -> str:
    normalized = text(value, label=label, maximum=200)
    if not _TAG_RE.fullmatch(normalized) or ".." in normalized:
        raise GitHubReleaseProductionError(f"{label} is not canonical")
    return normalized


def _single_file(directory: Path, *, label: str) -> Path:
    if directory.is_symlink():
        raise GitHubReleaseProductionError(f"{label} must not be a symlink")
    root = directory.resolve(strict=True)
    if not root.is_dir():
        raise GitHubReleaseProductionError(f"{label} must be a directory")
    entries = list(root.iterdir())
    if len(entries) != 1:
        raise GitHubReleaseProductionError(
            f"{label} must contain exactly one file, found {len(entries)}"
        )
    candidate = entries[0]
    if candidate.is_symlink() or not candidate.is_file():
        raise GitHubReleaseProductionError(f"{label} entry must be a regular file")
    return candidate


def _validate_selection(
    selection: dict[str, Any],
    *,
    expected_repository: str,
    expected_repository_id: int,
    expected_commit: str,
    expected_workflow: str,
    expected_run_id: int,
    expected_run_attempt: int,
) -> dict[str, Any]:
    if selection.get("schema_version") != 1 or selection.get("status") != "SELECTED":
        raise GitHubReleaseProductionError("source selection must be schema v1 SELECTED")
    repo = repository(expected_repository, label="expected repository")
    repo_id = positive_int(expected_repository_id, label="expected repository id")
    source_commit = commit(expected_commit, label="expected source commit")
    source_workflow = workflow(expected_workflow, label="expected source workflow")
    run_id = positive_int(expected_run_id, label="expected source run id")
    run_attempt = positive_int(
        expected_run_attempt, label="expected source run attempt"
    )
    expected = {
        "repository": repo,
        "repository_id": repo_id,
        "head_repository_id": repo_id,
        "head_branch": "main",
        "head_sha": source_commit,
        "workflow": source_workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }
    for key, value in expected.items():
        _require_equal(selection.get(key), value, label=f"source selection {key}")
    source_artifact = selection.get("artifact")
    if not isinstance(source_artifact, dict):
        raise GitHubReleaseProductionError("source selection lacks artifact metadata")
    expected_name = f"proofqa-transition-source-{source_commit}"
    _require_equal(
        artifact_name(source_artifact.get("name"), label="source artifact name"),
        expected_name,
        label="source artifact name",
    )
    return {
        "repository": repo,
        "repository_id": repo_id,
        "source_commit": source_commit,
        "source_workflow": source_workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifact": {
            "id": positive_int(source_artifact.get("id"), label="source artifact id"),
            "name": expected_name,
            "size_bytes": positive_int(
                source_artifact.get("size_bytes"), label="source artifact size"
            ),
            "digest": digest(
                source_artifact.get("digest"), label="source artifact digest"
            ),
        },
    }


def observe_release(
    *,
    release: dict[str, Any],
    expected_repository: str,
    expected_repository_id: int,
    expected_commit: str,
    expected_tag: str,
    expected_asset_name: str,
    expected_asset_digest: str | None = None,
    downloaded_asset: Path | None = None,
) -> dict[str, Any]:
    repo = repository(expected_repository, label="expected repository")
    repo_id = positive_int(expected_repository_id, label="expected repository id")
    source_commit = commit(expected_commit, label="expected commit")
    tag_name = _tag(expected_tag, label="expected release tag")
    asset_expected_name = artifact_name(
        expected_asset_name, label="expected release asset name"
    )

    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise GitHubReleaseProductionError(
            "release must be published, non-draft, and non-prerelease"
        )
    release_id = positive_int(release.get("id"), label="release id")
    _require_equal(release.get("tag_name"), tag_name, label="release tag")
    _require_equal(
        release.get("target_commitish"), source_commit, label="release target commit"
    )
    _require_equal(
        release.get("html_url"),
        f"https://github.com/{repo}/releases/tag/{tag_name}",
        label="release HTML URL",
    )
    _require_equal(
        release.get("url"),
        f"https://api.github.com/repos/{repo}/releases/{release_id}",
        label="release API URL",
    )

    assets = release.get("assets")
    if not isinstance(assets, list) or len(assets) != 1:
        raise GitHubReleaseProductionError(
            "release must contain exactly one immutable source asset"
        )
    asset = assets[0]
    if not isinstance(asset, dict):
        raise GitHubReleaseProductionError("release asset must be an object")
    asset_id = positive_int(asset.get("id"), label="release asset id")
    _require_equal(asset.get("name"), asset_expected_name, label="release asset name")
    _require_equal(asset.get("state"), "uploaded", label="release asset state")
    asset_size = positive_int(asset.get("size"), label="release asset size")
    expected_asset_api = (
        f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
    )
    _require_equal(asset.get("url"), expected_asset_api, label="release asset API URL")
    browser_url = (
        f"https://github.com/{repo}/releases/download/{tag_name}/{asset_expected_name}"
    )
    _require_equal(
        asset.get("browser_download_url"), browser_url, label="release asset download URL"
    )
    if asset.get("content_type") not in {
        "application/zip",
        "application/octet-stream",
    }:
        raise GitHubReleaseProductionError("release asset content type is not ZIP-compatible")

    api_digest: str | None = None
    raw_api_digest = asset.get("digest")
    if raw_api_digest is not None:
        api_digest = digest(raw_api_digest, label="release asset API digest")
    normalized_expected_digest = (
        digest(expected_asset_digest, label="expected release asset digest")
        if expected_asset_digest is not None
        else None
    )
    if api_digest is not None and normalized_expected_digest is not None:
        _require_equal(api_digest, normalized_expected_digest, label="release API digest")

    downloaded_digest: str | None = None
    if downloaded_asset is not None:
        if downloaded_asset.is_symlink() or not downloaded_asset.is_file():
            raise GitHubReleaseProductionError(
                "downloaded release asset must be a regular file"
            )
        _require_equal(
            downloaded_asset.name, asset_expected_name, label="downloaded asset filename"
        )
        _require_equal(
            downloaded_asset.stat().st_size,
            asset_size,
            label="downloaded asset size",
        )
        downloaded_digest = f"sha256:{sha256_file(downloaded_asset)}"
        if normalized_expected_digest is not None:
            _require_equal(
                downloaded_digest,
                normalized_expected_digest,
                label="downloaded release asset digest",
            )
        if api_digest is not None:
            _require_equal(
                downloaded_digest, api_digest, label="downloaded/API asset digest"
            )

    destination_id = (
        f"github-release:repository-id:{repo_id}:release-id:{release_id}:"
        f"asset-id:{asset_id}:tag:{tag_name}"
    )
    return {
        "schema_version": 1,
        "kind": "github-release-production-observation",
        "status": "OBSERVED",
        "repository": repo,
        "repository_id": repo_id,
        "source_commit": source_commit,
        "release": {
            "id": release_id,
            "tag": tag_name,
            "html_url": release["html_url"],
            "api_url": release["url"],
            "target_commitish": source_commit,
        },
        "asset": {
            "id": asset_id,
            "name": asset_expected_name,
            "size_bytes": asset_size,
            "api_url": expected_asset_api,
            "download_url": browser_url,
            "api_digest": api_digest,
            "downloaded_digest": downloaded_digest,
        },
        "destination_id": destination_id,
    }


def _write_source_json(path: Path, payload: dict[str, Any]) -> None:
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
    deployment_workflow: str,
    deployment_run_id: int,
    deployment_run_attempt: int,
    observation: dict[str, Any],
    subject_digest: str,
) -> dict[str, Any]:
    if output_dir.is_symlink() or output_dir.exists():
        raise GitHubReleaseProductionError(
            f"transition source output must not already exist: {output_dir}"
        )
    output = output_dir.resolve(strict=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / "evidence").mkdir()

    deployment_workflow = workflow(
        deployment_workflow, label="deployment workflow"
    )
    deployment_run_id = positive_int(deployment_run_id, label="deployment run id")
    deployment_run_attempt = positive_int(
        deployment_run_attempt, label="deployment run attempt"
    )
    subject_digest = digest(subject_digest, label="deployed subject digest")
    release = observation["release"]
    asset = observation["asset"]
    destination = {
        "environment": "ibex-customer-release",
        "identity": observation["destination_id"],
    }
    deployment = {
        "workflow": deployment_workflow,
        "run_id": deployment_run_id,
        "run_attempt": deployment_run_attempt,
        "event": "workflow_run",
        "branch": "main",
    }
    release_id = f"github-release/{release['id']}/{asset['id']}"
    transition_id = (
        f"github/release/{source_commit[:12]}/{deployment_run_id}/"
        f"{deployment_run_attempt}"
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
        "release API reported a published non-draft non-prerelease release",
        f"release tag {release['tag']} targeted the exact main-branch commit",
        "release contained exactly one expected transition-source ZIP asset",
        f"release asset {asset['id']} was in uploaded state with canonical API and download URLs",
        "live release asset bytes were re-downloaded after publication",
        "re-downloaded release asset size and SHA-256 matched the promoted source artifact",
        "repository numeric ID, release ID, asset ID, and tag were bound into the destination identity",
        "environment approval was not claimed because protection rules are tracked separately",
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
                "Publish the exact verified transition-source archive as one public, "
                "customer-consumable GitHub Release asset and observe it through the "
                "live release API and download service."
            ),
        },
        "evidence/action.json": {
            **common,
            "kind": "production-transition-action",
            "deployment": {
                "workflow": deployment_workflow,
                "run_id": deployment_run_id,
                "run_attempt": deployment_run_attempt,
            },
            "subject_digest": subject_digest,
            "status": "COMPLETED",
        },
        "evidence/result.json": {
            **common,
            "kind": "production-transition-result",
            "deployment_id": f"github-release/release/{release['id']}/asset/{asset['id']}",
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
        "release": {
            "release_id": release_id,
            "subject_digest": subject_digest,
        },
        "claim_boundary": _CLAIM_BOUNDARY,
        "files": inventory,
        "source_set_digest": f"sha256:{source_set_digest}",
    }


def build_production_source(
    *,
    source_download_dir: Path,
    source_selection: dict[str, Any],
    source_extracted_dir: Path,
    release: dict[str, Any],
    release_download_dir: Path,
    output_dir: Path,
    expected_repository: str,
    expected_repository_id: int,
    expected_commit: str,
    expected_source_workflow: str,
    expected_source_run_id: int,
    expected_source_run_attempt: int,
    expected_release_tag: str,
    expected_deployment_workflow: str,
    deployment_run_id: int,
    deployment_run_attempt: int,
) -> dict[str, Any]:
    selection = _validate_selection(
        source_selection,
        expected_repository=expected_repository,
        expected_repository_id=expected_repository_id,
        expected_commit=expected_commit,
        expected_workflow=expected_source_workflow,
        expected_run_id=expected_source_run_id,
        expected_run_attempt=expected_source_run_attempt,
    )
    source_archive = _single_file(source_download_dir, label="source download directory")
    source_digest = f"sha256:{sha256_file(source_archive)}"
    _require_equal(
        source_digest, selection["artifact"]["digest"], label="source archive digest"
    )
    extraction = extract_artifact(
        download_dir=source_download_dir,
        selection=source_selection,
        output_dir=source_extracted_dir,
    )
    source_destination = (
        f"github-actions:repository-id:{selection['repository_id']}:"
        "environment:ibex-evidence-release"
    )
    source_validation = validate_production_transition_source(
        source_dir=source_extracted_dir,
        expected_repository=selection["repository"],
        expected_commit=selection["source_commit"],
        expected_workflow=selection["source_workflow"],
        expected_run_id=selection["run_id"],
        expected_run_attempt=selection["run_attempt"],
        expected_event="workflow_run",
        expected_branch="main",
        expected_environment="ibex-evidence-release",
        expected_destination_id=source_destination,
    )
    asset_name = f"proofqa-transition-source-{selection['source_commit']}.zip"
    downloaded_asset = _single_file(
        release_download_dir, label="release download directory"
    )
    observation = observe_release(
        release=release,
        expected_repository=selection["repository"],
        expected_repository_id=selection["repository_id"],
        expected_commit=selection["source_commit"],
        expected_tag=expected_release_tag,
        expected_asset_name=asset_name,
        expected_asset_digest=source_digest,
        downloaded_asset=downloaded_asset,
    )
    source = _build_transition_source(
        output_dir=output_dir,
        repository_name=selection["repository"],
        source_commit=selection["source_commit"],
        deployment_workflow=expected_deployment_workflow,
        deployment_run_id=deployment_run_id,
        deployment_run_attempt=deployment_run_attempt,
        observation=observation,
        subject_digest=source_digest,
    )
    return {
        "schema_version": 1,
        "kind": "github-release-production-source-build",
        "status": "BUILT",
        "repository": selection["repository"],
        "source_commit": selection["source_commit"],
        "source_selection": selection,
        "source_extraction": {
            "status": extraction["status"],
            "files_checked": extraction["files_checked"],
            "archive": extraction["archive"],
        },
        "source_validation": {
            "status": source_validation["status"],
            "source_set_digest": source_validation["source_set_digest"],
        },
        "observation": observation,
        "production_source": {
            "transition_id": source["transition_id"],
            "deployment": source["deployment"],
            "destination": source["destination"],
            "release": source["release"],
            "claim_boundary": source["claim_boundary"],
            "files": source["files"],
            "source_set_digest": source["source_set_digest"],
        },
    }


def append_outputs(path: Path, observation: dict[str, Any]) -> None:
    if path.is_symlink() or path.is_dir():
        raise GitHubReleaseProductionError(f"GitHub output path is unsafe: {path}")
    values = {
        "destination-id": observation["destination_id"],
        "release-id": str(observation["release"]["id"]),
        "asset-id": str(observation["asset"]["id"]),
        "asset-digest": observation["asset"]["downloaded_digest"]
        or observation["asset"]["api_digest"]
        or "",
    }
    if any(not value or "\n" in value or "\r" in value for value in values.values()):
        raise GitHubReleaseProductionError("GitHub output is empty or contains a line break")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or observe production transition evidence for a GitHub Release"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--source-download-dir", type=Path, required=True)
    build.add_argument("--source-selection", type=Path, required=True)
    build.add_argument("--source-extracted-dir", type=Path, required=True)
    build.add_argument("--release-api-json", type=Path, required=True)
    build.add_argument("--release-download-dir", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--expected-repository", required=True)
    build.add_argument("--expected-repository-id", type=int, required=True)
    build.add_argument("--expected-commit", required=True)
    build.add_argument("--expected-source-workflow", required=True)
    build.add_argument("--expected-source-run-id", type=int, required=True)
    build.add_argument("--expected-source-run-attempt", type=int, required=True)
    build.add_argument("--expected-release-tag", required=True)
    build.add_argument("--expected-deployment-workflow", required=True)
    build.add_argument("--deployment-run-id", type=int, required=True)
    build.add_argument("--deployment-run-attempt", type=int, required=True)
    build.add_argument("--report", type=Path, required=True)
    build.add_argument("--github-output", type=Path)

    observe = subparsers.add_parser("observe")
    observe.add_argument("--release-api-json", type=Path, required=True)
    observe.add_argument("--source-provenance", type=Path, required=True)
    observe.add_argument("--expected-repository", required=True)
    observe.add_argument("--expected-repository-id", type=int, required=True)
    observe.add_argument("--expected-commit", required=True)
    observe.add_argument("--expected-release-tag", required=True)
    observe.add_argument("--expected-asset-name", required=True)
    observe.add_argument("--github-output", type=Path, required=True)
    observe.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        release = load_json_object(args.release_api_json, label="GitHub release API response")
        if args.command == "build":
            result = build_production_source(
                source_download_dir=args.source_download_dir,
                source_selection=load_json_object(
                    args.source_selection, label="source artifact selection"
                ),
                source_extracted_dir=args.source_extracted_dir,
                release=release,
                release_download_dir=args.release_download_dir,
                output_dir=args.output_dir,
                expected_repository=args.expected_repository,
                expected_repository_id=args.expected_repository_id,
                expected_commit=args.expected_commit,
                expected_source_workflow=args.expected_source_workflow,
                expected_source_run_id=args.expected_source_run_id,
                expected_source_run_attempt=args.expected_source_run_attempt,
                expected_release_tag=args.expected_release_tag,
                expected_deployment_workflow=args.expected_deployment_workflow,
                deployment_run_id=args.deployment_run_id,
                deployment_run_attempt=args.deployment_run_attempt,
            )
            observation = result["observation"]
            write_json(args.report, result, forbidden_root=args.output_dir)
            if args.github_output is not None:
                append_outputs(args.github_output, observation)
        else:
            provenance = load_json_object(
                args.source_provenance, label="production source provenance"
            )
            source_release = provenance.get("release")
            if not isinstance(source_release, dict):
                raise GitHubReleaseProductionError(
                    "production source provenance lacks release metadata"
                )
            observation = observe_release(
                release=release,
                expected_repository=args.expected_repository,
                expected_repository_id=args.expected_repository_id,
                expected_commit=args.expected_commit,
                expected_tag=args.expected_release_tag,
                expected_asset_name=args.expected_asset_name,
                expected_asset_digest=source_release.get("subject_digest"),
            )
            destination = provenance.get("destination")
            if not isinstance(destination, dict):
                raise GitHubReleaseProductionError(
                    "production source provenance lacks destination"
                )
            _require_equal(
                destination.get("environment"),
                "ibex-customer-release",
                label="source destination environment",
            )
            _require_equal(
                destination.get("identity"),
                observation["destination_id"],
                label="source/live destination identity",
            )
            write_json(args.report, observation)
            append_outputs(args.github_output, observation)
            result = observation
    except (
        OSError,
        ProductionTransitionSourceError,
        TrustedTransitionArtifactError,
        GitHubReleaseProductionError,
        ValueError,
    ) as error:
        print(f"GitHub release production source error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
