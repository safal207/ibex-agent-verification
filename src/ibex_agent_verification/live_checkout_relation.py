"""Live expected/observed relation for an exact GitHub Actions checkout."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .canonical_json import sha256_jcs
from .temporal_phase_relations import (
    TEMPORAL_RELATION_CONTEXT,
    TRANSITION_OBSERVATION_CONTEXT,
    compare_expected_to_observed,
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def compare_checkout_materialization(
    *,
    expected_head: str,
    actual_head: str,
    transition_id: str,
    observed_at: str,
    clean: bool,
) -> dict[str, Any]:
    """Compare the GitHub-declared head with the checkout actually observed.

    Inputs are explicit so the record can be independently replayed. The
    observation time defines a narrow five-minute relation validity window.
    """

    _require_sha(expected_head, "expected_head")
    _require_sha(actual_head, "actual_head")
    if not isinstance(transition_id, str) or not transition_id.strip():
        raise ValueError("transition_id must be a non-empty string")
    if not isinstance(clean, bool):
        raise TypeError("clean must be a boolean")
    observed_time = _parse_utc(observed_at)
    valid_from = observed_time - timedelta(minutes=5)
    valid_until = observed_time + timedelta(minutes=5)

    expected_digest = _head_digest(expected_head)
    actual_digest = _head_digest(actual_head)
    evidence_digest = sha256_jcs(
        {
            "expected_head": expected_head,
            "actual_head": actual_head,
            "transition_id": transition_id,
            "observed_at": _format_utc(observed_time),
            "clean": clean,
        }
    )
    expected = {
        "@context": TEMPORAL_RELATION_CONTEXT,
        "source": {
            "artifact_id": "github-event:pull-request-head",
            "artifact_type": "git-commit",
            "digest": expected_digest,
        },
        "target": {
            "artifact_id": "runner:workspace-checkout",
            "artifact_type": "git-worktree",
            "digest": expected_digest,
        },
        "relation_type": "PR_HEAD_MATERIALIZED_AS_CHECKOUT",
        "transition_id": transition_id,
        "expected_phase": "CI_VERIFICATION",
        "valid_from": _format_utc(valid_from),
        "valid_until": _format_utc(valid_until),
        "evidence_max_age_seconds": 60,
        "expected_outcome": {"status": "MATERIALIZED", "clean": True},
        "evidence_refs": [
            {
                "ref": f"github://transition/{transition_id}",
                "digest": evidence_digest,
                "captured_at": _format_utc(observed_time),
            }
        ],
    }
    observed = {
        "@context": TRANSITION_OBSERVATION_CONTEXT,
        "source": {
            "artifact_id": "github-event:pull-request-head",
            "artifact_type": "git-commit",
            "digest": actual_digest,
        },
        "target": {
            "artifact_id": "runner:workspace-checkout",
            "artifact_type": "git-worktree",
            "digest": actual_digest,
        },
        "relation_type": "PR_HEAD_MATERIALIZED_AS_CHECKOUT",
        "transition_id": transition_id,
        "observed_phase": "CI_VERIFICATION",
        "observed_at": _format_utc(observed_time),
        "observed_outcome": {"status": "MATERIALIZED", "clean": clean},
        "evidence_refs": [
            {
                "ref": f"github://transition/{transition_id}",
                "digest": evidence_digest,
                "captured_at": _format_utc(observed_time),
            }
        ],
    }
    return {
        "expected": expected,
        "observed": observed,
        "comparison": compare_expected_to_observed(expected, observed),
    }


def _head_digest(head: str) -> str:
    return f"sha256:{hashlib.sha256(head.encode('ascii')).hexdigest()}"


def _require_sha(value: str, label: str) -> None:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ValueError(f"{label} must be 40 lowercase hexadecimal characters")


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("observed_at must be an RFC3339 UTC timestamp ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("observed_at must be UTC")
    return parsed


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
