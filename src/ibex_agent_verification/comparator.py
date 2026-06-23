from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import TraceEvent


@dataclass(frozen=True)
class ComparisonResult:
    status: str
    expected_events: int
    actual_events: int
    first_mismatch_index: int | None
    differences: dict[str, dict[str, Any]]

    @property
    def matches(self) -> bool:
        return self.status == "MATCH"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "expected_events": self.expected_events,
            "actual_events": self.actual_events,
            "first_mismatch_index": self.first_mismatch_index,
            "differences": self.differences,
        }


def compare_traces(expected: list[TraceEvent], actual: list[TraceEvent]) -> ComparisonResult:
    shared_length = min(len(expected), len(actual))

    for index in range(shared_length):
        left = expected[index].normalized()
        right = actual[index].normalized()
        if left != right:
            keys = sorted(set(left) | set(right))
            differences = {
                key: {"expected": left.get(key), "actual": right.get(key)}
                for key in keys
                if left.get(key) != right.get(key)
            }
            return ComparisonResult(
                status="MISMATCH",
                expected_events=len(expected),
                actual_events=len(actual),
                first_mismatch_index=index,
                differences=differences,
            )

    if len(expected) != len(actual):
        return ComparisonResult(
            status="MISMATCH",
            expected_events=len(expected),
            actual_events=len(actual),
            first_mismatch_index=shared_length,
            differences={
                "trace_length": {
                    "expected": len(expected),
                    "actual": len(actual),
                }
            },
        )

    return ComparisonResult(
        status="MATCH",
        expected_events=len(expected),
        actual_events=len(actual),
        first_mismatch_index=None,
        differences={},
    )
