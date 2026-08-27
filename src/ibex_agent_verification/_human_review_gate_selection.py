"""Review evidence normalization and decisive-state selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .canonical_json import sha256_jcs
from ._human_review_receipt_model import (
    ALLOWED_PERMISSIONS,
    DECISIVE_STATES,
    format_utc,
    parse_utc,
    positive_integer,
    require_exact_keys,
    require_mapping,
    require_text,
    validate_sha,
)


def latest_decisive_reviews(
    reviews: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized = normalize_reviews(reviews)
    latest: dict[str, dict[str, Any]] = {}
    for review in normalized:
        if review["state"] not in DECISIVE_STATES:
            continue
        prior = latest.get(review["reviewer"])
        if prior is None or review_sort_key(review) > review_sort_key(prior):
            latest[review["reviewer"]] = review
    return latest


def normalize_reviews(
    reviews: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(reviews, Sequence) or isinstance(
        reviews, (str, bytes)
    ):
        raise TypeError("reviews must be an array")
    allowed = {
        "review_id", "reviewer", "state", "commit_id",
        "submitted_at", "review_url", "reviewer_permission",
    }
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, raw in enumerate(reviews):
        review = require_mapping(raw, f"reviews[{index}]")
        require_exact_keys(review, allowed, f"reviews[{index}]")
        review_id = positive_integer(
            review["review_id"], f"reviews[{index}].review_id"
        )
        if review_id in seen:
            raise ValueError("review ids must be unique")
        seen.add(review_id)
        commit_id = require_text(
            review["commit_id"], f"reviews[{index}].commit_id"
        )
        validate_sha(commit_id, f"reviews[{index}].commit_id")
        item = {
            "review_id": review_id,
            "reviewer": require_text(
                review["reviewer"], f"reviews[{index}].reviewer"
            ),
            "state": require_text(
                review["state"], f"reviews[{index}].state"
            ).upper(),
            "commit_id": commit_id,
            "submitted_at": format_utc(parse_utc(
                review["submitted_at"],
                f"reviews[{index}].submitted_at",
            )),
            "review_url": require_text(
                review["review_url"], f"reviews[{index}].review_url"
            ),
            "reviewer_permission": require_text(
                review["reviewer_permission"],
                f"reviews[{index}].reviewer_permission",
            ).lower(),
        }
        item["evidence_digest"] = review_evidence_digest(item)
        normalized.append(item)
    return normalized


def rejection_reason(
    review: Mapping[str, Any],
    author: str,
    current_head: str,
    observed_time: datetime,
) -> dict[str, Any] | None:
    reviewer = review["reviewer"]
    if reviewer.casefold() == author.casefold():
        return {"code": "SELF_REVIEW", "reviewer": reviewer}
    if review["reviewer_permission"] not in ALLOWED_PERMISSIONS:
        return {
            "code": "INSUFFICIENT_PERMISSION",
            "reviewer": reviewer,
            "permission": review["reviewer_permission"],
        }
    if review["state"] != "APPROVED":
        return {
            "code": f"REVIEW_{review['state']}",
            "reviewer": reviewer,
        }
    if review["commit_id"] != current_head:
        return {
            "code": "STALE_HEAD",
            "reviewer": reviewer,
            "review_head": review["commit_id"],
            "current_head": current_head,
        }
    if parse_utc(review["submitted_at"], "submitted_at") > observed_time:
        return {"code": "FUTURE_REVIEW", "reviewer": reviewer}
    return None


def review_sort_key(
    review: Mapping[str, Any],
) -> tuple[datetime, int]:
    return (
        parse_utc(review["submitted_at"], "submitted_at"),
        int(review["review_id"]),
    )


def review_evidence_digest(review: Mapping[str, Any]) -> str:
    return sha256_jcs({
        "review_id": review["review_id"],
        "reviewer": review["reviewer"],
        "state": review["state"],
        "commit_id": review["commit_id"],
        "submitted_at": review["submitted_at"],
        "review_url": review["review_url"],
        "reviewer_permission": review["reviewer_permission"],
    })
