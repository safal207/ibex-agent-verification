#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


class TrustedReceiptError(ValueError):
    """Raised when a public receipt cannot be rendered safely."""


_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_URL_PREFIX = "https://github.com/"


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TrustedReceiptError(f"{label} must be a regular non-symlink file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TrustedReceiptError(f"{path}: invalid {label} JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise TrustedReceiptError(f"{label} must be a JSON object")
    return value


def _positive_int(value: str, *, label: str) -> int:
    if not value.isdigit() or int(value) <= 0:
        raise TrustedReceiptError(f"{label} must be a positive integer")
    return int(value)


def _digest(value: str, *, label: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise TrustedReceiptError(f"{label} must be a SHA-256 digest")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def render_receipt(
    *,
    audit: dict[str, Any],
    repository: str,
    source_commit: str,
    producer_run_id: str,
    trigger_run_id: str,
    artifact_id: str,
    artifact_url: str,
    artifact_digest: str,
) -> str:
    if audit.get("schema_version") != 1 or audit.get("status") != "VERIFIED":
        raise TrustedReceiptError("final audit must be schema v1 VERIFIED")
    if audit.get("repository") != repository:
        raise TrustedReceiptError("final audit repository mismatch")
    if audit.get("source_commit") != source_commit:
        raise TrustedReceiptError("final audit source commit mismatch")
    if not _COMMIT_RE.fullmatch(source_commit):
        raise TrustedReceiptError("source commit must be 40 lowercase hexadecimal characters")
    if not repository or "/" not in repository or len(repository) > 200:
        raise TrustedReceiptError("repository must use owner/name form")
    expected_url_prefix = f"{_URL_PREFIX}{repository}/actions/runs/"
    if not artifact_url.startswith(expected_url_prefix) or len(artifact_url) > 500:
        raise TrustedReceiptError("artifact URL must point to this repository's Actions run")

    manifest_digest = _digest(str(audit.get("manifest_sha256", "")), label="manifest")
    receipt_digest = _digest(str(audit.get("receipt_sha256", "")), label="receipt")
    report_digest = _digest(str(audit.get("gate_report_sha256", "")), label="gate report")
    sigstore_digest = _digest(
        str(audit.get("sigstore_bundle_sha256", "")),
        label="Sigstore bundle",
    )
    artifact_digest = _digest(artifact_digest, label="artifact")
    claim_boundary = audit.get("claim_boundary")
    if (
        not isinstance(claim_boundary, str)
        or not claim_boundary.strip()
        or len(claim_boundary) > 1000
        or "not a production deployment claim" not in claim_boundary
    ):
        raise TrustedReceiptError("final audit claim boundary is missing or too broad")

    payload = {
        "artifact": {
            "digest": artifact_digest,
            "id": _positive_int(artifact_id, label="artifact id"),
            "url": artifact_url,
        },
        "attestation_status": "VERIFIED",
        "claim_boundary": claim_boundary,
        "gate_decision": "PASS",
        "gate_report_digest": report_digest,
        "manifest_digest": manifest_digest,
        "producer_run_id": _positive_int(producer_run_id, label="producer run id"),
        "producer_workflow": ".github/workflows/trusted-transition-manifest.yml",
        "receipt_digest": receipt_digest,
        "repository": repository,
        "schema_version": 1,
        "sigstore_bundle_digest": sigstore_digest,
        "source_commit": source_commit,
        "trigger_run_id": _positive_int(trigger_run_id, label="trigger run id"),
        "type": "trusted-transition-reference-receipt",
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    return (
        "<!-- trusted-transition-reference-receipt -->\n"
        "### Trusted transition reference receipt\n\n"
        "```json\n"
        f"{rendered}\n"
        "```\n\n"
        "This comment is a discovery index. The artifact digest and Sigstore evidence are authoritative.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a trusted transition receipt comment")
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--producer-run-id", required=True)
    parser.add_argument("--trigger-run-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        audit = _load_object(args.audit, label="final audit")
        body = render_receipt(
            audit=audit,
            repository=args.repository,
            source_commit=args.source_commit,
            producer_run_id=args.producer_run_id,
            trigger_run_id=args.trigger_run_id,
            artifact_id=args.artifact_id,
            artifact_url=args.artifact_url,
            artifact_digest=args.artifact_digest,
        )
        if args.output.is_symlink() or args.output.is_dir():
            raise TrustedReceiptError(
                f"output must be a writable regular-file path: {args.output}"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8", newline="\n")
    except (OSError, TrustedReceiptError, ValueError) as error:
        print(f"trusted receipt error: {error}", file=sys.stderr)
        return 2
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
