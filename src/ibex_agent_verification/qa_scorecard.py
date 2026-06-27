from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable

from .qa_benchmark import QABenchmarkError


_COMPLETED_STATUSES = {"PASS", "FAIL"}
_ALLOWED_STATUSES = {
    "PASS",
    "FAIL",
    "INVALID_RESPONSE",
    "OUTPUT_TRUNCATED",
    "INFERENCE_FAILED",
}
_TIMING_FIELDS = (
    "duration_ms",
    "time_to_first_output_ms",
    "generation_ms",
)


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator * 100.0 / denominator, 6)


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    position = (len(ordered) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return round(ordered[lower_index], 6)
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    interpolated = lower + (upper - lower) * (position - lower_index)
    return round(interpolated, 6)


def _distribution(values: list[float]) -> dict[str, int | float | None]:
    if not values:
        return {
            "count": 0,
            "minimum": None,
            "p50": None,
            "p95": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "minimum": round(min(values), 6),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "maximum": round(max(values), 6),
    }


def _validated_score(report: dict[str, Any], *, task_id: str) -> tuple[int, int]:
    score = report.get("score")
    if not isinstance(score, dict):
        raise QABenchmarkError(f"QA task report {task_id} lacks score")
    earned = score.get("earned")
    possible = score.get("possible")
    if (
        isinstance(earned, bool)
        or not isinstance(earned, int)
        or isinstance(possible, bool)
        or not isinstance(possible, int)
        or earned < 0
        or possible <= 0
        or earned > possible
    ):
        raise QABenchmarkError(f"QA task report {task_id} has invalid score")
    return earned, possible


def _provider_outcome(report: dict[str, Any]) -> str:
    status = report["status"]
    inference_status = report.get("inference_status")
    http_status = report.get("http_status")

    if inference_status == "COMPLETE":
        if isinstance(http_status, int) and not isinstance(http_status, bool):
            return "success" if 200 <= http_status < 300 else "failure"
        return "unknown"
    if inference_status == "REQUEST_FAILED" or status == "INFERENCE_FAILED":
        return "failure"
    return "unknown"


def _provider_failure_class(report: dict[str, Any]) -> str:
    http_status = report.get("http_status")
    if http_status == 429:
        return "http_429"
    if isinstance(http_status, int) and not isinstance(http_status, bool):
        if 400 <= http_status < 500:
            return "http_4xx"
        if 500 <= http_status < 600:
            return "http_5xx"
        return "unexpected_http_status"
    return "transport_timeout_or_unknown"


def _validated_timing(report: dict[str, Any], *, task_id: str) -> dict[str, float | None]:
    timing = report.get("timing")
    if timing is None:
        return {field: None for field in _TIMING_FIELDS}
    if not isinstance(timing, dict):
        raise QABenchmarkError(f"QA task report {task_id} timing must be an object")

    normalized: dict[str, float | None] = {}
    for field in _TIMING_FIELDS:
        value = timing.get(field)
        if value is None:
            normalized[field] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise QABenchmarkError(
                f"QA task report {task_id} timing.{field} must be a finite non-negative number or null"
            )
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise QABenchmarkError(
                f"QA task report {task_id} timing.{field} must be a finite non-negative number or null"
            )
        normalized[field] = number
    return normalized


def build_reliability_scorecard(
    reports: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build orthogonal QA metrics without hiding failure classes in one percentage."""

    items = list(reports)
    if not items:
        raise QABenchmarkError("QA reliability scorecard requires at least one task report")

    outcomes: Counter[str] = Counter()
    provider_failures: Counter[str] = Counter()
    end_to_end_earned = 0
    end_to_end_possible = 0
    completed_earned = 0
    completed_possible = 0
    completed_tasks = 0
    provider_successes = 0
    provider_failed = 0
    provider_unknown = 0

    all_duration_ms: list[float] = []
    successful_duration_ms: list[float] = []
    successful_ttft_ms: list[float] = []
    successful_generation_ms: list[float] = []

    task_results: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()
    for index, report in enumerate(items):
        if not isinstance(report, dict):
            raise QABenchmarkError(f"QA task report at index {index} must be an object")
        task_id = report.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise QABenchmarkError(f"QA task report at index {index} has invalid task_id")
        if task_id in seen_task_ids:
            raise QABenchmarkError(f"duplicate QA task report in scorecard: {task_id}")
        seen_task_ids.add(task_id)

        status = report.get("status")
        if status not in _ALLOWED_STATUSES:
            raise QABenchmarkError(
                f"QA task report {task_id} has unsupported status: {status!r}"
            )
        earned, possible = _validated_score(report, task_id=task_id)
        timing = _validated_timing(report, task_id=task_id)
        end_to_end_earned += earned
        end_to_end_possible += possible
        outcomes[status] += 1

        answer_completed = status in _COMPLETED_STATUSES
        if answer_completed:
            completed_tasks += 1
            completed_earned += earned
            completed_possible += possible

        provider_outcome = _provider_outcome(report)
        if provider_outcome == "success":
            provider_successes += 1
        elif provider_outcome == "failure":
            provider_failed += 1
            provider_failures[_provider_failure_class(report)] += 1
        else:
            provider_unknown += 1

        duration_ms = timing["duration_ms"]
        if duration_ms is not None:
            all_duration_ms.append(duration_ms)
        if provider_outcome == "success":
            if duration_ms is not None:
                successful_duration_ms.append(duration_ms)
            if timing["time_to_first_output_ms"] is not None:
                successful_ttft_ms.append(timing["time_to_first_output_ms"])
            if timing["generation_ms"] is not None:
                successful_generation_ms.append(timing["generation_ms"])

        task_results.append(
            {
                "task_id": task_id,
                "status": status,
                "answer_completed": answer_completed,
                "provider_outcome": provider_outcome,
                "score": {
                    "earned": earned,
                    "possible": possible,
                    "percent": _percent(earned, possible),
                },
                "timing": timing,
            }
        )

    total_tasks = len(items)
    provider_observed = provider_successes + provider_failed
    return {
        "schema_version": 2,
        "end_to_end_score": {
            "earned": end_to_end_earned,
            "possible": end_to_end_possible,
            "percent": _percent(end_to_end_earned, end_to_end_possible),
            "definition": (
                "Field-level points across every configured task; incomplete and provider-failed "
                "tasks retain their full denominator."
            ),
        },
        "answer_correctness": {
            "earned": completed_earned,
            "possible": completed_possible,
            "percent": _percent(completed_earned, completed_possible),
            "tasks_evaluated": completed_tasks,
            "definition": (
                "Field-level correctness only for tasks that produced a valid strict-JSON "
                "answer and were scored PASS or FAIL."
            ),
        },
        "completion_reliability": {
            "completed": completed_tasks,
            "total": total_tasks,
            "percent": _percent(completed_tasks, total_tasks),
            "definition": (
                "Share of configured tasks that produced a valid strict-JSON answer; invalid, "
                "truncated, and inference-failed tasks are not completed."
            ),
        },
        "provider_reliability": {
            "successful": provider_successes,
            "failed": provider_failed,
            "unknown": provider_unknown,
            "observed": provider_observed,
            "total": total_tasks,
            "percent": _percent(provider_successes, provider_observed),
            "failure_classes": dict(sorted(provider_failures.items())),
            "definition": (
                "Share of requests with known provider outcomes that completed with HTTP 2xx. "
                "Output truncation and invalid model JSON remain provider successes when the "
                "request itself completed successfully."
            ),
        },
        "time_performance": {
            "clock": "client_monotonic",
            "unit": "milliseconds",
            "all_observed_requests": _distribution(all_duration_ms),
            "successful_requests": {
                "duration_ms": _distribution(successful_duration_ms),
                "time_to_first_output_ms": _distribution(successful_ttft_ms),
                "generation_ms": _distribution(successful_generation_ms),
            },
            "provider_failed_requests_excluded": provider_failed,
            "provider_unknown_requests_excluded": provider_unknown,
            "definition": (
                "Client-observed monotonic timing distributions. The release policy may apply "
                "an explicit latency SLO to successful HTTP-2xx request duration p95. Provider "
                "failures are excluded here and remain visible on the provider axis."
            ),
        },
        "outcomes": {
            "pass": outcomes["PASS"],
            "fail": outcomes["FAIL"],
            "invalid_response": outcomes["INVALID_RESPONSE"],
            "output_truncated": outcomes["OUTPUT_TRUNCATED"],
            "inference_failed": outcomes["INFERENCE_FAILED"],
        },
        "task_results": task_results,
        "claim_boundary": (
            "These axes separate answer correctness, answer completion, provider request "
            "reliability, and client-observed timing for this exact run. They do not establish "
            "stable quality or latency without repeated samples."
        ),
    }
