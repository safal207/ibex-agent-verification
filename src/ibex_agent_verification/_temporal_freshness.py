"""Fail-closed evidence freshness calculation."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any


def stale_evidence(
    refs: Sequence[Mapping[str, Any]],
    observed_at: datetime,
    max_age_seconds: int,
    parse_utc: Callable[[Any, str], datetime],
) -> list[dict[str, Any]]:
    """Return evidence mismatches without truncating fractional age."""

    mismatches: list[dict[str, Any]] = []
    limit = timedelta(seconds=max_age_seconds)
    for evidence in refs:
        captured_at = parse_utc(evidence["captured_at"], "captured_at")
        age = observed_at - captured_at
        if captured_at > observed_at:
            mismatches.append({
                "field": "evidence_refs",
                "ref": evidence["ref"],
                "reason": "evidence was captured after the observation",
            })
        elif age > limit:
            mismatches.append({
                "field": "evidence_refs",
                "ref": evidence["ref"],
                "reason": "evidence exceeded the declared freshness window",
                "age_seconds": math.ceil(age.total_seconds()),
                "max_age_seconds": max_age_seconds,
            })
    return mismatches
