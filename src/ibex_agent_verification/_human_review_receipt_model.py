"""Canonical HumanReviewReceiptV1 model and validators."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .canonical_json import canonicalize_jcs, sha256_jcs

HUMAN_REVIEW_RECEIPT_CONTEXT = (
    "urn:ibex-agent-verification:human-review-receipt:v1"
)
HUMAN_REVIEW_GATE_CONTEXT = "urn:ibex-agent-verification:human-review-gate:v1"

ALLOWED_PERMISSIONS = {"write", "maintain", "admin"}
DECISIVE_STATES = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]+$"
)


def validate_human_review_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    value = require_mapping(receipt, "receipt")
    allowed = {
        "@context", "repository", "pull_request_number", "head_sha",
        "review_id", "reviewer", "reviewer_permission", "review_state",
        "phase", "submitted_at", "review_url", "policy_version",
        "observed_at", "dismissed", "evidence_digest",
    }
    require_exact_keys(value, allowed, "receipt")
    if value["@context"] != HUMAN_REVIEW_RECEIPT_CONTEXT:
        raise ValueError("receipt @context is not HumanReviewReceiptV1")

    repository = validate_repository(value["repository"])
    pull_request_number = positive_integer(
        value["pull_request_number"], "pull_request_number"
    )
    review_id = positive_integer(value["review_id"], "review_id")
    validate_sha(value["head_sha"], "head_sha")

    permission = require_text(
        value["reviewer_permission"], "reviewer_permission"
    ).lower()
    if permission not in ALLOWED_PERMISSIONS:
        raise ValueError("reviewer_permission is not binding")
    if value["review_state"] != "APPROVED":
        raise ValueError("review_state must be APPROVED")
    if value["phase"] != "PRE_MERGE":
        raise ValueError("phase must be PRE_MERGE")
    if value["dismissed"] is not False:
        raise ValueError("dismissed must be false")

    submitted_at = parse_utc(value["submitted_at"], "submitted_at")
    observed_at = parse_utc(value["observed_at"], "observed_at")
    if submitted_at > observed_at:
        raise ValueError("submitted_at cannot be after observed_at")

    evidence_digest = require_text(
        value["evidence_digest"], "evidence_digest"
    )
    if SHA256.fullmatch(evidence_digest) is None:
        raise ValueError("evidence_digest must be a lowercase sha256 digest")

    normalized = {
        "@context": HUMAN_REVIEW_RECEIPT_CONTEXT,
        "repository": repository,
        "pull_request_number": pull_request_number,
        "head_sha": value["head_sha"],
        "review_id": review_id,
        "reviewer": require_text(value["reviewer"], "reviewer"),
        "reviewer_permission": permission,
        "review_state": "APPROVED",
        "phase": "PRE_MERGE",
        "submitted_at": format_utc(submitted_at),
        "review_url": require_text(value["review_url"], "review_url"),
        "policy_version": require_text(
            value["policy_version"], "policy_version"
        ),
        "observed_at": format_utc(observed_at),
        "dismissed": False,
        "evidence_digest": evidence_digest,
    }
    canonicalize_jcs(normalized)
    return normalized


def human_review_receipt_id(receipt: Mapping[str, Any]) -> str:
    value = dict(require_mapping(receipt, "receipt"))
    claimed = value.pop("receipt_id", None)
    computed = sha256_jcs(validate_human_review_receipt(value))
    if claimed is not None and claimed != computed:
        raise ValueError("receipt_id does not recompute")
    return computed


def validate_repository(value: Any) -> str:
    repository = require_text(value, "repository")
    if REPOSITORY.fullmatch(repository) is None:
        raise ValueError("repository must be a canonical owner/name identifier")
    return repository


def positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def require_exact_keys(
    value: Mapping[str, Any], allowed: set[str], label: str
) -> None:
    missing = sorted(allowed - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        raise ValueError(
            f"{label} keys mismatch: missing={missing}, extra={extra}"
        )


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def validate_sha(value: Any, label: str) -> None:
    if not isinstance(value, str) or SHA40.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be 40 lowercase hexadecimal characters"
        )


def parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(
            f"{label} must be an RFC3339 UTC timestamp ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(
            f"{label} must be a valid RFC3339 UTC timestamp"
        ) from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{label} must be UTC")
    return parsed


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
