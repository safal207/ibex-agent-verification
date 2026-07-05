"""Binding human-review receipts for exact pull-request transitions.

A GitHub approval is only evidence for the exact head, reviewer authority, phase,
and observation time that were independently reconstructed. The resulting gate
record never grants merge authority.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from .canonical_json import CanonicalizationError, canonicalize_jcs, sha256_jcs
from .temporal_phase_relations import (
    MATCH,
    TEMPORAL_RELATION_CONTEXT,
    TRANSITION_OBSERVATION_CONTEXT,
    compare_expected_to_observed,
)

HUMAN_REVIEW_RECEIPT_CONTEXT = (
    "urn:ibex-agent-verification:human-review-receipt:v1"
)
HUMAN_REVIEW_GATE_CONTEXT = "urn:ibex-agent-verification:human-review-gate:v1"

_ALLOWED_PERMISSIONS = {"write", "maintain", "admin"}
_DECISIVE_STATES = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def evaluate_human_review_gate(
    *,
    repository: str,
    pull_request_number: int,
    current_head: str,
    author: str,
    reviews: Sequence[Mapping[str, Any]],
    observed_at: str,
    policy_version: str,
) -> dict[str, Any]:
    """Select a current eligible approval and emit a non-authorizing gate record.

    Only the latest decisive review per reviewer is considered. A new commit,
    dismissal, change request, self-review, insufficient permission, or future
    timestamp invalidates that review for the current transition.
    """

    try:
        repository = _validate_repository(repository)
        pull_request_number = _positive_integer(
            pull_request_number, "pull_request_number"
        )
        _validate_sha(current_head, "current_head")
        author = _require_text(author, "author")
        policy_version = _require_text(policy_version, "policy_version")
        observed_time = _parse_utc(observed_at, "observed_at")
        normalized_reviews = _normalize_reviews(reviews)
    except (CanonicalizationError, KeyError, TypeError, ValueError) as exc:
        return _gate_record(
            status="NON_RECOMPUTABLE",
            current_head=current_head if isinstance(current_head, str) else None,
            receipt=None,
            relation_bundle=None,
            reasons=[{"code": "INVALID_INPUT", "detail": str(exc)}],
        )

    latest_by_reviewer: dict[str, dict[str, Any]] = {}
    for review in normalized_reviews:
        if review["state"] not in _DECISIVE_STATES:
            continue
        prior = latest_by_reviewer.get(review["reviewer"])
        if prior is None or _review_sort_key(review) > _review_sort_key(prior):
            latest_by_reviewer[review["reviewer"]] = review

    candidates: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    for reviewer in sorted(latest_by_reviewer):
        review = latest_by_reviewer[reviewer]
        rejection = _rejection_reason(
            review=review,
            author=author,
            current_head=current_head,
            observed_time=observed_time,
        )
        if rejection is None:
            candidates.append(review)
        else:
            reasons.append(rejection)

    if not candidates:
        if not latest_by_reviewer:
            reasons.append(
                {
                    "code": "NO_DECISIVE_REVIEWS",
                    "detail": "no APPROVED, CHANGES_REQUESTED, or DISMISSED review was observed",
                }
            )
        return _gate_record(
            status="REQUIRED_EXTERNAL",
            current_head=current_head,
            receipt=None,
            relation_bundle=None,
            reasons=reasons,
        )

    selected = max(candidates, key=_review_sort_key)
    receipt_without_id = {
        "@context": HUMAN_REVIEW_RECEIPT_CONTEXT,
        "repository": repository,
        "pull_request_number": pull_request_number,
        "head_sha": current_head,
        "review_id": selected["review_id"],
        "reviewer": selected["reviewer"],
        "reviewer_permission": selected["reviewer_permission"],
        "review_state": "APPROVED",
        "phase": "PRE_MERGE",
        "submitted_at": selected["submitted_at"],
        "review_url": selected["review_url"],
        "policy_version": policy_version,
        "observed_at": _format_utc(observed_time),
        "dismissed": False,
        "evidence_digest": _review_evidence_digest(selected),
    }
    receipt = validate_human_review_receipt(receipt_without_id)
    receipt["receipt_id"] = sha256_jcs(receipt)

    relation_bundle = _build_relation_bundle(
        repository=repository,
        pull_request_number=pull_request_number,
        current_head=current_head,
        selected=selected,
        receipt=receipt,
        observed_time=observed_time,
    )
    if relation_bundle["comparison"]["status"] != MATCH:
        return _gate_record(
            status="NON_RECOMPUTABLE",
            current_head=current_head,
            receipt=receipt,
            relation_bundle=relation_bundle,
            reasons=[
                {
                    "code": "RELATION_COMPARISON_FAILED",
                    "detail": relation_bundle["comparison"]["status"],
                }
            ],
        )

    return _gate_record(
        status="SATISFIED",
        current_head=current_head,
        receipt=receipt,
        relation_bundle=relation_bundle,
        reasons=[],
    )


def validate_human_review_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and normalize HumanReviewReceiptV1 without its receipt_id."""

    value = _require_mapping(receipt, "receipt")
    allowed = {
        "@context",
        "repository",
        "pull_request_number",
        "head_sha",
        "review_id",
        "reviewer",
        "reviewer_permission",
        "review_state",
        "phase",
        "submitted_at",
        "review_url",
        "policy_version",
        "observed_at",
        "dismissed",
        "evidence_digest",
    }
    _require_exact_keys(value, allowed, "receipt")
    if value["@context"] != HUMAN_REVIEW_RECEIPT_CONTEXT:
        raise ValueError("receipt @context is not HumanReviewReceiptV1")

    repository = _validate_repository(value["repository"])
    pull_request_number = _positive_integer(
        value["pull_request_number"], "pull_request_number"
    )
    review_id = _positive_integer(value["review_id"], "review_id")
    _validate_sha(value["head_sha"], "head_sha")

    permission = _require_text(
        value["reviewer_permission"], "reviewer_permission"
    ).lower()
    if permission not in _ALLOWED_PERMISSIONS:
        raise ValueError("reviewer_permission is not binding")
    if value["review_state"] != "APPROVED":
        raise ValueError("review_state must be APPROVED")
    if value["phase"] != "PRE_MERGE":
        raise ValueError("phase must be PRE_MERGE")
    if value["dismissed"] is not False:
        raise ValueError("dismissed must be false")

    submitted_at = _parse_utc(value["submitted_at"], "submitted_at")
    observed_at = _parse_utc(value["observed_at"], "observed_at")
    if submitted_at > observed_at:
        raise ValueError("submitted_at cannot be after observed_at")

    evidence_digest = _require_text(
        value["evidence_digest"], "evidence_digest"
    )
    if _SHA256.fullmatch(evidence_digest) is None:
        raise ValueError("evidence_digest must be a lowercase sha256 digest")

    normalized = {
        "@context": HUMAN_REVIEW_RECEIPT_CONTEXT,
        "repository": repository,
        "pull_request_number": pull_request_number,
        "head_sha": value["head_sha"],
        "review_id": review_id,
        "reviewer": _require_text(value["reviewer"], "reviewer"),
        "reviewer_permission": permission,
        "review_state": "APPROVED",
        "phase": "PRE_MERGE",
        "submitted_at": _format_utc(submitted_at),
        "review_url": _require_text(value["review_url"], "review_url"),
        "policy_version": _require_text(value["policy_version"], "policy_version"),
        "observed_at": _format_utc(observed_at),
        "dismissed": False,
        "evidence_digest": evidence_digest,
    }
    canonicalize_jcs(normalized)
    return normalized


def human_review_receipt_id(receipt: Mapping[str, Any]) -> str:
    """Recompute and validate a receipt identifier."""

    value = dict(_require_mapping(receipt, "receipt"))
    claimed = value.pop("receipt_id", None)
    computed = sha256_jcs(validate_human_review_receipt(value))
    if claimed is not None and claimed != computed:
        raise ValueError("receipt_id does not recompute")
    return computed


def _build_relation_bundle(
    *,
    repository: str,
    pull_request_number: int,
    current_head: str,
    selected: Mapping[str, Any],
    receipt: Mapping[str, Any],
    observed_time: datetime,
) -> dict[str, Any]:
    head_digest = "sha256:" + hashlib.sha256(
        current_head.encode("ascii")
    ).hexdigest()
    receipt_digest = str(receipt["receipt_id"])
    transition_id = (
        f"github://{repository}/pull/{pull_request_number}/"
        f"merge-candidate/{current_head}"
    )
    evidence_ref = {
        "ref": selected["review_url"],
        "digest": selected["evidence_digest"],
        "captured_at": _format_utc(observed_time),
    }
    outcome = {
        "status": "APPROVED",
        "dismissed": False,
        "eligible_reviewer": True,
    }
    source = {
        "artifact_id": f"git:{repository}@{current_head}",
        "artifact_type": "git-commit",
        "digest": head_digest,
    }
    target = {
        "artifact_id": f"github-review:{selected['review_id']}",
        "artifact_type": "human-review-receipt",
        "digest": receipt_digest,
    }
    expected = {
        "@context": TEMPORAL_RELATION_CONTEXT,
        "source": source,
        "target": target,
        "relation_type": "BINDING_REVIEW_SUPPORTS_HEAD",
        "transition_id": transition_id,
        "expected_phase": "PRE_MERGE",
        "valid_from": selected["submitted_at"],
        "valid_until": _format_utc(observed_time + timedelta(minutes=5)),
        "evidence_max_age_seconds": 60,
        "expected_outcome": outcome,
        "evidence_refs": [evidence_ref],
    }
    observed = {
        "@context": TRANSITION_OBSERVATION_CONTEXT,
        "source": source,
        "target": target,
        "relation_type": "BINDING_REVIEW_SUPPORTS_HEAD",
        "transition_id": transition_id,
        "observed_phase": "PRE_MERGE",
        "observed_at": _format_utc(observed_time),
        "observed_outcome": outcome,
        "evidence_refs": [evidence_ref],
    }
    return {
        "expected": expected,
        "observed": observed,
        "comparison": compare_expected_to_observed(expected, observed),
    }


def _gate_record(
    *,
    status: str,
    current_head: str | None,
    receipt: dict[str, Any] | None,
    relation_bundle: dict[str, Any] | None,
    reasons: list[dict[str, Any]],
) -> dict[str, Any]:
    record = {
        "@context": HUMAN_REVIEW_GATE_CONTEXT,
        "status": status,
        "current_head": current_head,
        "receipt": receipt,
        "relation_bundle": relation_bundle,
        "gate_satisfied": status == "SATISFIED",
        "merge_authorized": False,
        "blocking": status != "SATISFIED",
        "reasons": reasons,
        "permitted_next_transition": (
            "EVALUATE_REPOSITORY_MERGE_POLICY"
            if status == "SATISFIED"
            else "REQUEST_BINDING_HUMAN_REVIEW"
            if status == "REQUIRED_EXTERNAL"
            else "BLOCK_AND_REPAIR_EVIDENCE"
        ),
    }
    record["gate_record_id"] = sha256_jcs(record)
    return record


def _normalize_reviews(
    reviews: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(reviews, Sequence) or isinstance(reviews, (str, bytes)):
        raise TypeError("reviews must be an array")

    allowed = {
        "review_id",
        "reviewer",
        "state",
        "commit_id",
        "submitted_at",
        "review_url",
        "reviewer_permission",
    }
    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, raw_review in enumerate(reviews):
        review = _require_mapping(raw_review, f"reviews[{index}]")
        _require_exact_keys(review, allowed, f"reviews[{index}]")
        review_id = _positive_integer(
            review["review_id"], f"reviews[{index}].review_id"
        )
        if review_id in seen_ids:
            raise ValueError("review ids must be unique")
        seen_ids.add(review_id)

        commit_id = _require_text(
            review["commit_id"], f"reviews[{index}].commit_id"
        )
        _validate_sha(commit_id, f"reviews[{index}].commit_id")
        submitted_at = _format_utc(
            _parse_utc(review["submitted_at"], f"reviews[{index}].submitted_at")
        )
        normalized_review = {
            "review_id": review_id,
            "reviewer": _require_text(
                review["reviewer"], f"reviews[{index}].reviewer"
            ),
            "state": _require_text(
                review["state"], f"reviews[{index}].state"
            ).upper(),
            "commit_id": commit_id,
            "submitted_at": submitted_at,
            "review_url": _require_text(
                review["review_url"], f"reviews[{index}].review_url"
            ),
            "reviewer_permission": _require_text(
                review["reviewer_permission"],
                f"reviews[{index}].reviewer_permission",
            ).lower(),
        }
        normalized_review["evidence_digest"] = _review_evidence_digest(
            normalized_review
        )
        normalized.append(normalized_review)
    return normalized


def _rejection_reason(
    *,
    review: Mapping[str, Any],
    author: str,
    current_head: str,
    observed_time: datetime,
) -> dict[str, Any] | None:
    reviewer = review["reviewer"]
    if reviewer.casefold() == author.casefold():
        return {"code": "SELF_REVIEW", "reviewer": reviewer}
    if review["reviewer_permission"] not in _ALLOWED_PERMISSIONS:
        return {
            "code": "INSUFFICIENT_PERMISSION",
            "reviewer": reviewer,
            "permission": review["reviewer_permission"],
        }
    if review["state"] != "APPROVED":
        return {"code": f"REVIEW_{review['state']}", "reviewer": reviewer}
    if review["commit_id"] != current_head:
        return {
            "code": "STALE_HEAD",
            "reviewer": reviewer,
            "review_head": review["commit_id"],
            "current_head": current_head,
        }
    submitted_at = _parse_utc(review["submitted_at"], "submitted_at")
    if submitted_at > observed_time:
        return {"code": "FUTURE_REVIEW", "reviewer": reviewer}
    return None


def _review_sort_key(review: Mapping[str, Any]) -> tuple[datetime, int]:
    return (
        _parse_utc(review["submitted_at"], "submitted_at"),
        int(review["review_id"]),
    )


def _review_evidence_digest(review: Mapping[str, Any]) -> str:
    return sha256_jcs(
        {
            "review_id": review["review_id"],
            "reviewer": review["reviewer"],
            "state": review["state"],
            "commit_id": review["commit_id"],
            "submitted_at": review["submitted_at"],
            "review_url": review["review_url"],
            "reviewer_permission": review["reviewer_permission"],
        }
    )


def _validate_repository(value: Any) -> str:
    repository = _require_text(value, "repository")
    owner, separator, name = repository.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise ValueError("repository must be owner/name")
    return repository


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], allowed: set[str], label: str
) -> None:
    missing = sorted(allowed - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        raise ValueError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _validate_sha(value: Any, label: str) -> None:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ValueError(f"{label} must be 40 lowercase hexadecimal characters")


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid RFC3339 UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{label} must be UTC")
    return parsed


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
