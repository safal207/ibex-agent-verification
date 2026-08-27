"""Exact-head HumanReviewReceiptV1 gate runtime."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from .canonical_json import CanonicalizationError, sha256_jcs
from ._human_review_gate_selection import (
    latest_decisive_reviews,
    rejection_reason,
    review_sort_key,
)
from ._human_review_receipt_model import (
    HUMAN_REVIEW_GATE_CONTEXT,
    HUMAN_REVIEW_RECEIPT_CONTEXT,
    format_utc,
    parse_utc,
    positive_integer,
    require_text,
    validate_human_review_receipt,
    validate_repository,
    validate_sha,
)
from .temporal_phase_relations import (
    MATCH,
    TEMPORAL_RELATION_CONTEXT,
    TRANSITION_OBSERVATION_CONTEXT,
    compare_expected_to_observed,
)


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
    """Evaluate current GitHub reviews for one exact PRE_MERGE head."""

    try:
        repository = validate_repository(repository)
        pull_request_number = positive_integer(
            pull_request_number, "pull_request_number"
        )
        validate_sha(current_head, "current_head")
        author = require_text(author, "author")
        policy_version = require_text(policy_version, "policy_version")
        observed_time = parse_utc(observed_at, "observed_at")
        latest = latest_decisive_reviews(reviews)
    except (CanonicalizationError, KeyError, TypeError, ValueError) as exc:
        return _gate_record(
            status="NON_RECOMPUTABLE",
            current_head=current_head if isinstance(current_head, str) else None,
            receipt=None,
            relation_bundle=None,
            reasons=[{"code": "INVALID_INPUT", "detail": str(exc)}],
        )

    candidates: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    for reviewer in sorted(latest):
        review = latest[reviewer]
        rejection = rejection_reason(
            review, author, current_head, observed_time
        )
        if rejection is None:
            candidates.append(review)
        else:
            reasons.append(rejection)

    if not candidates:
        if not latest:
            reasons.append(
                {
                    "code": "NO_DECISIVE_REVIEWS",
                    "detail": (
                        "no APPROVED, CHANGES_REQUESTED, or DISMISSED "
                        "review was observed"
                    ),
                }
            )
        return _gate_record(
            status="REQUIRED_EXTERNAL",
            current_head=current_head,
            receipt=None,
            relation_bundle=None,
            reasons=reasons,
        )

    selected = max(candidates, key=review_sort_key)
    receipt = validate_human_review_receipt(
        {
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
            "observed_at": format_utc(observed_time),
            "dismissed": False,
            "evidence_digest": selected["evidence_digest"],
        }
    )
    receipt["receipt_id"] = sha256_jcs(receipt)

    relation_bundle = _relation_bundle(
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


def _relation_bundle(
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
    transition_id = (
        f"github://{repository}/pull/{pull_request_number}/"
        f"merge-candidate/{current_head}"
    )
    source = {
        "artifact_id": f"git:{repository}@{current_head}",
        "artifact_type": "git-commit",
        "digest": head_digest,
    }
    target = {
        "artifact_id": f"github-review:{selected['review_id']}",
        "artifact_type": "human-review-receipt",
        "digest": receipt["receipt_id"],
    }
    evidence = [
        {
            "ref": selected["review_url"],
            "digest": selected["evidence_digest"],
            "captured_at": format_utc(observed_time),
        }
    ]
    outcome = {
        "status": "APPROVED",
        "dismissed": False,
        "eligible_reviewer": True,
    }
    expected = {
        "@context": TEMPORAL_RELATION_CONTEXT,
        "source": source,
        "target": target,
        "relation_type": "BINDING_REVIEW_SUPPORTS_HEAD",
        "transition_id": transition_id,
        "expected_phase": "PRE_MERGE",
        "valid_from": selected["submitted_at"],
        "valid_until": format_utc(observed_time + timedelta(minutes=5)),
        "evidence_max_age_seconds": 60,
        "expected_outcome": outcome,
        "evidence_refs": evidence,
    }
    observed = {
        "@context": TRANSITION_OBSERVATION_CONTEXT,
        "source": source,
        "target": target,
        "relation_type": "BINDING_REVIEW_SUPPORTS_HEAD",
        "transition_id": transition_id,
        "observed_phase": "PRE_MERGE",
        "observed_at": format_utc(observed_time),
        "observed_outcome": outcome,
        "evidence_refs": evidence,
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
