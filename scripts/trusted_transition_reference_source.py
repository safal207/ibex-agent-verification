#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.trusted_transition_artifact import (
        EXPECTED_SOURCE_FILES,
        TrustedTransitionArtifactError,
        commit,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
        write_json,
    )
except ImportError:
    from trusted_transition_artifact import (
        EXPECTED_SOURCE_FILES,
        TrustedTransitionArtifactError,
        commit,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
        write_json,
    )


REFERENCE_CLAIM_BOUNDARY = (
    "This signed reference bundle verifies trusted cross-workflow artifact ingestion "
    "and manifest signing. It is not a production deployment claim."
)


def _inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": relative,
            "size_bytes": (root / relative).stat().st_size,
            "sha256": sha256_file(root / relative),
        }
        for relative in sorted(EXPECTED_SOURCE_FILES)
    ]


def build_reference_source(
    *,
    output_dir: Path,
    repository_name: str,
    source_commit: str,
    workflow_path: str,
    run_id: int,
    run_attempt: int,
    event: str,
    branch: str,
    subject_path: Path,
) -> dict[str, Any]:
    repo = repository(repository_name, label="repository")
    source_sha = commit(source_commit, label="source commit")
    workflow_file = workflow(workflow_path, label="workflow")
    run_id = positive_int(run_id, label="run id")
    run_attempt = positive_int(run_attempt, label="run attempt")
    event = text(event, label="event", maximum=100)
    branch = text(branch, label="branch", maximum=200)
    if subject_path.is_symlink() or not subject_path.is_file():
        raise TrustedTransitionArtifactError(
            f"reference subject must be a regular non-symlink file: {subject_path}"
        )
    if output_dir.is_symlink() or output_dir.exists():
        raise TrustedTransitionArtifactError(
            f"reference source output directory must not already exist: {output_dir}"
        )
    root = output_dir.resolve(strict=False)
    (root / "evidence").mkdir(parents=True, exist_ok=False)

    short = source_sha[:12]
    release_id = f"reference-{short}-{run_id}-{run_attempt}"
    transition_id = f"reference/artifact-ingestion/{short}/{run_id}/{run_attempt}"
    destination = {
        "environment": "reference",
        "identity": "proofqa:trusted-artifact-ingestion",
    }
    deployment = {
        "workflow": workflow_file,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "event": event,
        "branch": branch,
    }
    subject_digest = f"sha256:{sha256_file(subject_path)}"
    common = {
        "schema_version": 1,
        "transition_id": transition_id,
        "repository": repo,
        "source_commit": source_sha,
        "release_id": release_id,
        "destination": destination,
    }
    payloads: dict[str, dict[str, Any]] = {
        "source-provenance.json": {
            "schema_version": 1,
            "kind": "production-transition-source",
            "repository": repo,
            "source_commit": source_sha,
            "deployment": deployment,
            "destination": destination,
            "release": {
                "release_id": release_id,
                "subject_digest": subject_digest,
            },
            "claim_boundary": REFERENCE_CLAIM_BOUNDARY,
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
            "claim_boundary": REFERENCE_CLAIM_BOUNDARY,
        },
        "evidence/intent.json": {
            **common,
            "kind": "production-transition-intent",
            "statement": (
                "Publish one immutable reference transition source artifact for "
                "trusted cross-workflow ingestion validation."
            ),
        },
        "evidence/action.json": {
            **common,
            "kind": "production-transition-action",
            "deployment": {
                "workflow": workflow_file,
                "run_id": run_id,
                "run_attempt": run_attempt,
            },
            "subject_digest": subject_digest,
            "status": "COMPLETED",
        },
        "evidence/result.json": {
            **common,
            "kind": "production-transition-result",
            "deployment_id": f"workflow-run/{run_id}/{run_attempt}",
            "subject_digest": subject_digest,
            "status": "SUCCEEDED",
        },
        "evidence/verification.json": {
            **common,
            "kind": "production-transition-verification",
            "subject_digest": subject_digest,
            "observed_destination": destination,
            "status": "VERIFIED",
            "checks": [
                "reference subject digest computed from repository bytes",
                "source bundle prepared for cross-workflow artifact ingestion",
            ],
        },
    }
    for relative, payload in payloads.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    inventory = _inventory(root)
    source_set = hashlib.sha256(
        json.dumps(inventory, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "kind": "trusted-transition-reference-source-build",
        "status": "BUILT",
        "repository": repo,
        "source_commit": source_sha,
        "deployment": deployment,
        "destination": destination,
        "release": {"release_id": release_id, "subject_digest": subject_digest},
        "claim_boundary": REFERENCE_CLAIM_BOUNDARY,
        "files": inventory,
        "files_written": len(inventory),
        "source_set_digest": f"sha256:{source_set}",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one deterministic reference transition source artifact"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--subject-path", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_reference_source(
            output_dir=args.output_dir,
            repository_name=args.repository,
            source_commit=args.source_commit,
            workflow_path=args.workflow,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            event=args.event,
            branch=args.branch,
            subject_path=args.subject_path,
        )
        if args.report is not None:
            write_json(args.report, result, forbidden_root=args.output_dir)
    except (OSError, TrustedTransitionArtifactError, ValueError) as error:
        print(f"trusted transition reference source error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
