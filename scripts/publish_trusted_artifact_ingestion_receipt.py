#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


class IngestionReceiptError(ValueError):
    """Raised when a trusted artifact-ingestion receipt is unsafe or inconsistent."""


_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_WORKFLOW_RE = re.compile(r"^\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml$")
_RECEIPT_MARKER = "<!-- trusted-transition-artifact-ingestion-receipt -->"
_PRODUCER_WORKFLOW = ".github/workflows/trusted-transition-artifact.yml"


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise IngestionReceiptError(
            f"{label} must be a regular non-symlink file: {path}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise IngestionReceiptError(
            f"{path}: invalid {label} JSON: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise IngestionReceiptError(f"{label} must be a JSON object")
    return value


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise IngestionReceiptError(f"{label} must be a positive integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    else:
        raise IngestionReceiptError(f"{label} must be a positive integer")
    if number <= 0:
        raise IngestionReceiptError(f"{label} must be a positive integer")
    return number


def _digest(value: Any, *, label: str) -> str:
    normalized = str(value)
    if not _SHA256_RE.fullmatch(normalized):
        raise IngestionReceiptError(f"{label} must be a SHA-256 digest")
    return normalized if normalized.startswith("sha256:") else f"sha256:{normalized}"


def _artifact_name(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _ARTIFACT_NAME_RE.fullmatch(value):
        raise IngestionReceiptError(f"{label} must be a canonical artifact name")
    return value


def _workflow(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _WORKFLOW_RE.fullmatch(value):
        raise IngestionReceiptError(f"{label} must be a canonical workflow path")
    path = PurePosixPath(value)
    if (
        path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.parts[:2] != (".github", "workflows")
    ):
        raise IngestionReceiptError(f"{label} must be a canonical workflow path")
    return value


def render_receipt(
    *,
    audit: dict[str, Any],
    repository: str,
    source_commit: str,
    producer_run_id: Any,
    source_run_id: Any,
    final_artifact_id: Any,
    final_artifact_url: str,
    final_artifact_digest: Any,
) -> str:
    if audit.get("schema_version") != 1 or audit.get("status") != "VERIFIED":
        raise IngestionReceiptError("final audit must be schema v1 VERIFIED")
    if not repository or repository.count("/") != 1 or len(repository) > 200:
        raise IngestionReceiptError("repository must use owner/name form")
    if audit.get("repository") != repository:
        raise IngestionReceiptError("final audit repository mismatch")
    if not _COMMIT_RE.fullmatch(source_commit):
        raise IngestionReceiptError(
            "source commit must be 40 lowercase hexadecimal characters"
        )
    if audit.get("source_commit") != source_commit:
        raise IngestionReceiptError("final audit source commit mismatch")
    source_workflow = _workflow(
        audit.get("source_workflow"), label="audited source workflow"
    )

    source_artifact = audit.get("source_artifact")
    if not isinstance(source_artifact, dict):
        raise IngestionReceiptError("final audit lacks source artifact identity")
    audited_source_run_id = _positive_int(
        source_artifact.get("run_id"), label="audited source run id"
    )
    supplied_source_run_id = _positive_int(source_run_id, label="source run id")
    if audited_source_run_id != supplied_source_run_id:
        raise IngestionReceiptError("source workflow run mismatch")

    source_artifact_id = _positive_int(
        source_artifact.get("id"), label="source artifact id"
    )
    source_artifact_name = _artifact_name(
        source_artifact.get("name"), label="source artifact name"
    )
    expected_source_name = f"proofqa-transition-source-{source_commit}"
    if source_artifact_name != expected_source_name:
        raise IngestionReceiptError("source artifact name does not bind the commit")
    source_artifact_digest = _digest(
        source_artifact.get("digest"), label="source artifact"
    )
    source_run_attempt = _positive_int(
        source_artifact.get("run_attempt"), label="source run attempt"
    )

    producer_run = _positive_int(producer_run_id, label="producer run id")
    final_id = _positive_int(final_artifact_id, label="final artifact id")
    expected_url = (
        f"https://github.com/{repository}/actions/runs/{producer_run}/artifacts/{final_id}"
    )
    if final_artifact_url != expected_url:
        raise IngestionReceiptError("final artifact URL identity mismatch")

    claim_boundary = audit.get("claim_boundary")
    if (
        not isinstance(claim_boundary, str)
        or not claim_boundary.strip()
        or len(claim_boundary) > 1000
        or "not a production deployment claim" not in claim_boundary
    ):
        raise IngestionReceiptError("final audit claim boundary is missing or too broad")

    payload = {
        "attestation_status": "VERIFIED",
        "claim_boundary": claim_boundary,
        "final_artifact": {
            "digest": _digest(final_artifact_digest, label="final artifact"),
            "id": final_id,
            "url": final_artifact_url,
        },
        "gate_decision": "PASS",
        "gate_report_digest": _digest(
            audit.get("gate_report_sha256"), label="gate report"
        ),
        "manifest_digest": _digest(
            audit.get("manifest_sha256"), label="manifest"
        ),
        "producer_run_id": producer_run,
        "producer_workflow": _PRODUCER_WORKFLOW,
        "receipt_digest": _digest(
            audit.get("receipt_sha256"), label="manifest receipt"
        ),
        "repository": repository,
        "schema_version": 1,
        "sigstore_bundle_digest": _digest(
            audit.get("sigstore_bundle_sha256"), label="Sigstore bundle"
        ),
        "source_artifact": {
            "digest": source_artifact_digest,
            "id": source_artifact_id,
            "name": source_artifact_name,
        },
        "source_commit": source_commit,
        "source_run_attempt": source_run_attempt,
        "source_run_id": supplied_source_run_id,
        "source_workflow": source_workflow,
        "type": "trusted-transition-artifact-ingestion-receipt",
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    return (
        f"{_RECEIPT_MARKER}\n"
        "### Trusted transition artifact-ingestion receipt\n\n"
        "```json\n"
        f"{rendered}\n"
        "```\n\n"
        "This comment is a discovery index. The final artifact digest, signed manifest, "
        "Sigstore bundle, and verification reports are authoritative.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render one trusted artifact-ingestion receipt comment"
    )
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--producer-run-id", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--final-artifact-id", required=True)
    parser.add_argument("--final-artifact-url", required=True)
    parser.add_argument("--final-artifact-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        body = render_receipt(
            audit=_load_object(args.audit, label="final audit"),
            repository=args.repository,
            source_commit=args.source_commit,
            producer_run_id=args.producer_run_id,
            source_run_id=args.source_run_id,
            final_artifact_id=args.final_artifact_id,
            final_artifact_url=args.final_artifact_url,
            final_artifact_digest=args.final_artifact_digest,
        )
        if args.output.is_symlink() or args.output.is_dir():
            raise IngestionReceiptError(
                f"output must be a writable regular-file path: {args.output}"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8", newline="\n")
    except (OSError, IngestionReceiptError, ValueError) as error:
        print(f"trusted artifact-ingestion receipt error: {error}", file=sys.stderr)
        return 2
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
