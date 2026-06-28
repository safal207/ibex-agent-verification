#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.trusted_transition_artifact import (
        EXPECTED_SOURCE_FILES,
        TrustedTransitionArtifactError,
        commit,
        digest,
        load_json_object,
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
        digest,
        load_json_object,
        positive_int,
        repository,
        sha256_file,
        text,
        workflow,
        write_json,
    )


_CLAIM_LIMITATION_MARKERS = (
    "not a production deployment claim",
    "not a physical production execution claim",
)
ATTESTED_SIGNER_FILES = {
    "signer/source-artifacts-api.json",
    "signer/source-artifact-selection.json",
    "signer/source-artifact-extraction.json",
    "signer/live-release.json",
    "signer/runtime-observation.json",
    "signer/source-validation.json",
}
EXPECTED_ATTESTED_FILES = EXPECTED_SOURCE_FILES | ATTESTED_SIGNER_FILES


def _claim_boundary(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 2000
        or not any(marker in value for marker in _CLAIM_LIMITATION_MARKERS)
    ):
        raise TrustedTransitionArtifactError(
            "source claim boundary must contain an explicit production limitation"
        )
    return value.strip()


def audit_signed_reference(
    *,
    root_dir: Path,
    expected_repository: str,
    expected_commit: str,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_source_workflow: str,
    expected_signer_workflow: str,
) -> dict[str, Any]:
    """Audit the exact signed runtime source and its signer-side observations."""
    root = root_dir.resolve(strict=True)
    repo = repository(expected_repository, label="expected repository")
    source_commit = commit(expected_commit, label="expected commit")
    run_id = positive_int(expected_run_id, label="expected run id")
    run_attempt = positive_int(expected_run_attempt, label="expected run attempt")
    source_workflow = workflow(
        expected_source_workflow, label="expected source workflow"
    )
    signer = text(
        expected_signer_workflow,
        label="expected signer workflow",
        maximum=500,
    )

    bundle = root / "bundle"
    manifest_path = bundle / "manifest.json"
    provenance_path = bundle / "source-provenance.json"
    receipt_path = root / "manifest-receipt.json"
    report_path = root / "proofqa-gate-report.json"
    sigstore_path = root / "manifest.sigstore.json"
    selection_path = bundle / "signer/source-artifact-selection.json"
    extraction_path = bundle / "signer/source-artifact-extraction.json"
    observation_path = bundle / "signer/runtime-observation.json"
    validation_path = bundle / "signer/source-validation.json"

    manifest = load_json_object(manifest_path, label="transition manifest")
    provenance = load_json_object(provenance_path, label="source provenance")
    receipt = load_json_object(receipt_path, label="manifest receipt")
    report = load_json_object(report_path, label="ProofQA gate report")
    load_json_object(sigstore_path, label="Sigstore bundle")
    selection = load_json_object(selection_path, label="artifact selection")
    extraction = load_json_object(extraction_path, label="artifact extraction")
    observation = load_json_object(observation_path, label="runtime observation")
    validation = load_json_object(validation_path, label="source validation")

    if provenance.get("repository") != repo:
        raise TrustedTransitionArtifactError("source provenance repository mismatch")
    if provenance.get("source_commit") != source_commit:
        raise TrustedTransitionArtifactError("source provenance commit mismatch")
    if provenance.get("kind") != "production-transition-source":
        raise TrustedTransitionArtifactError("unexpected source provenance kind")
    claim_boundary = _claim_boundary(provenance.get("claim_boundary"))
    deployment = provenance.get("deployment")
    if not isinstance(deployment, dict):
        raise TrustedTransitionArtifactError("source provenance deployment is missing")
    if (
        deployment.get("run_id") != run_id
        or deployment.get("run_attempt") != run_attempt
    ):
        raise TrustedTransitionArtifactError("source provenance run identity mismatch")
    if deployment.get("workflow") != source_workflow:
        raise TrustedTransitionArtifactError("source provenance workflow mismatch")

    files = manifest.get("files")
    if not isinstance(files, list):
        raise TrustedTransitionArtifactError("manifest files must be an array")
    paths = {
        item.get("path")
        for item in files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if (
        paths != EXPECTED_ATTESTED_FILES
        or len(files) != len(EXPECTED_ATTESTED_FILES)
    ):
        raise TrustedTransitionArtifactError(
            "manifest inventory is not the exact source plus signer-evidence set"
        )

    if selection.get("schema_version") != 1 or selection.get("status") != "SELECTED":
        raise TrustedTransitionArtifactError("artifact selection is not SELECTED")
    if (
        selection.get("repository") != repo
        or selection.get("head_sha") != source_commit
    ):
        raise TrustedTransitionArtifactError("artifact selection identity mismatch")
    if (
        selection.get("run_id") != run_id
        or selection.get("run_attempt") != run_attempt
    ):
        raise TrustedTransitionArtifactError("artifact selection run identity mismatch")
    if selection.get("workflow") != source_workflow:
        raise TrustedTransitionArtifactError("artifact selection workflow mismatch")
    source_artifact = selection.get("artifact")
    if not isinstance(source_artifact, dict):
        raise TrustedTransitionArtifactError(
            "artifact selection lacks source artifact"
        )
    source_artifact_digest = digest(
        source_artifact.get("digest"), label="source artifact digest"
    )

    if extraction.get("schema_version") != 1 or extraction.get("status") != "EXTRACTED":
        raise TrustedTransitionArtifactError("artifact extraction is not EXTRACTED")
    if extraction.get("files_checked") != len(EXPECTED_SOURCE_FILES):
        raise TrustedTransitionArtifactError("artifact extraction file count mismatch")
    archive = extraction.get("archive")
    if (
        not isinstance(archive, dict)
        or archive.get("digest") != source_artifact_digest
    ):
        raise TrustedTransitionArtifactError("artifact extraction digest mismatch")

    if (
        observation.get("schema_version") != 1
        or observation.get("status") != "OBSERVED"
    ):
        raise TrustedTransitionArtifactError("runtime observation is not OBSERVED")
    if (
        observation.get("repository") != repo
        or observation.get("source_commit") != source_commit
    ):
        raise TrustedTransitionArtifactError("runtime observation identity mismatch")
    if (
        observation.get("runtime_workflow") != source_workflow
        or observation.get("runtime_run_id") != run_id
        or observation.get("runtime_run_attempt") != run_attempt
    ):
        raise TrustedTransitionArtifactError(
            "runtime observation workflow identity mismatch"
        )
    if observation.get("claim_boundary") != claim_boundary:
        raise TrustedTransitionArtifactError(
            "runtime observation claim boundary mismatch"
        )
    destination = provenance.get("destination")
    if (
        not isinstance(destination, dict)
        or observation.get("destination_id") != destination.get("identity")
    ):
        raise TrustedTransitionArtifactError(
            "runtime observation destination mismatch"
        )

    if validation.get("schema_version") != 1 or validation.get("status") != "VALIDATED":
        raise TrustedTransitionArtifactError("source validation is not VALIDATED")
    if (
        validation.get("repository") != repo
        or validation.get("source_commit") != source_commit
    ):
        raise TrustedTransitionArtifactError("source validation identity mismatch")
    validation_deployment = validation.get("deployment")
    if (
        not isinstance(validation_deployment, dict)
        or validation_deployment.get("workflow") != source_workflow
        or validation_deployment.get("run_id") != run_id
        or validation_deployment.get("run_attempt") != run_attempt
    ):
        raise TrustedTransitionArtifactError(
            "source validation workflow identity mismatch"
        )
    if validation.get("files_checked") != len(EXPECTED_SOURCE_FILES):
        raise TrustedTransitionArtifactError("source validation file count mismatch")
    if validation.get("claim_boundary") != claim_boundary:
        raise TrustedTransitionArtifactError(
            "source validation claim boundary mismatch"
        )

    attestation = receipt.get("attestation")
    if not isinstance(attestation, dict) or attestation.get("status") != "VERIFIED":
        raise TrustedTransitionArtifactError("manifest attestation is not VERIFIED")
    if attestation.get("repository") != repo:
        raise TrustedTransitionArtifactError(
            "manifest attestation repository mismatch"
        )
    if attestation.get("signer_workflow") != signer:
        raise TrustedTransitionArtifactError("manifest attestation signer mismatch")
    if attestation.get("deny_self_hosted_runners") is not True:
        raise TrustedTransitionArtifactError("self-hosted runners were not denied")

    if report.get("schema_version") != 4 or report.get("decision") != "PASS":
        raise TrustedTransitionArtifactError(
            "final ProofQA report is not schema v4 PASS"
        )
    transition_manifest = report.get("transition_manifest")
    if not isinstance(transition_manifest, dict):
        raise TrustedTransitionArtifactError(
            "ProofQA report lacks transition manifest"
        )
    report_attestation = transition_manifest.get("attestation")
    if (
        not isinstance(report_attestation, dict)
        or report_attestation.get("status") != "VERIFIED"
    ):
        raise TrustedTransitionArtifactError(
            "ProofQA report lacks VERIFIED attestation"
        )
    manifest_sha = sha256_file(manifest_path)
    source = report.get("source")
    if (
        not isinstance(source, dict)
        or source.get("transition_manifest_sha256") != manifest_sha
    ):
        raise TrustedTransitionArtifactError("ProofQA manifest digest mismatch")

    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "repository": repo,
        "source_commit": source_commit,
        "source_workflow": source_workflow,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": sha256_file(receipt_path),
        "gate_report_sha256": sha256_file(report_path),
        "sigstore_bundle_sha256": sha256_file(sigstore_path),
        "files_checked": len(files),
        "claim_boundary": claim_boundary,
        "source_artifact": {
            "id": source_artifact.get("id"),
            "name": source_artifact.get("name"),
            "digest": source_artifact_digest,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        "selection_report_sha256": sha256_file(selection_path),
        "extraction_report_sha256": sha256_file(extraction_path),
        "runtime_observation_sha256": sha256_file(observation_path),
        "source_validation_sha256": sha256_file(validation_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit one signed cross-workflow transition trust chain"
    )
    parser.add_argument("--root-dir", type=Path, required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-run-id", type=int, required=True)
    parser.add_argument("--expected-run-attempt", type=int, required=True)
    parser.add_argument("--expected-source-workflow", required=True)
    parser.add_argument("--expected-signer-workflow", required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = audit_signed_reference(
            root_dir=args.root_dir,
            expected_repository=args.expected_repository,
            expected_commit=args.expected_commit,
            expected_run_id=args.expected_run_id,
            expected_run_attempt=args.expected_run_attempt,
            expected_source_workflow=args.expected_source_workflow,
            expected_signer_workflow=args.expected_signer_workflow,
        )
        write_json(
            args.report,
            result,
            forbidden_root=args.root_dir / "bundle",
        )
    except (OSError, TrustedTransitionArtifactError, ValueError) as error:
        print(f"trusted transition artifact audit error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
