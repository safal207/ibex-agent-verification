from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from .inference_evidence import analyze_capture, load_capture


class QABenchmarkError(ValueError):
    """Raised when a QA benchmark corpus or response is unsafe or malformed."""


_SUITE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{2,79}$")
_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_SENSITIVE_KEYS = {"authorization", "api_key", "api-key", "x-api-key"}


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise QABenchmarkError(f"{label} must be a regular non-symlink file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise QABenchmarkError(f"{path}: invalid {label} JSON: {error.msg}") from error
    except OSError as error:
        raise QABenchmarkError(f"cannot read {label} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise QABenchmarkError(f"{label} must be a JSON object")
    return payload


def _find_sensitive_key(value: Any, *, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child = f"{path}.{key_text}"
            if key_text.lower() in _SENSITIVE_KEYS:
                return child
            found = _find_sensitive_key(item, path=child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_sensitive_key(item, path=f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise QABenchmarkError(f"{path} must not contain NaN or infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise QABenchmarkError(f"{path} keys must be non-empty strings")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise QABenchmarkError(f"{path} contains unsupported JSON value {type(value).__name__}")


def load_qa_suite(path: Path) -> dict[str, Any]:
    suite = _load_json_object(path, label="QA benchmark suite")
    if suite.get("schema_version") != 1:
        raise QABenchmarkError("QA benchmark suite schema_version must equal 1")

    suite_id = suite.get("suite_id")
    if not isinstance(suite_id, str) or not _SUITE_ID_RE.fullmatch(suite_id):
        raise QABenchmarkError(f"invalid QA benchmark suite_id: {suite_id!r}")
    title = suite.get("title")
    if not isinstance(title, str) or not title.strip():
        raise QABenchmarkError("QA benchmark title must be a non-empty string")
    boundary = suite.get("claim_boundary")
    if not isinstance(boundary, str) or not boundary.strip():
        raise QABenchmarkError("QA benchmark claim_boundary must be a non-empty string")

    tasks = suite.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 100:
        raise QABenchmarkError("QA benchmark tasks must contain from 1 through 100 items")

    task_ids: set[str] = set()
    normalized_tasks: list[dict[str, Any]] = []
    for index, raw_task in enumerate(tasks):
        if not isinstance(raw_task, dict):
            raise QABenchmarkError(f"tasks[{index}] must be an object")
        task_id = raw_task.get("id")
        if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
            raise QABenchmarkError(f"tasks[{index}].id is invalid: {task_id!r}")
        if task_id in task_ids:
            raise QABenchmarkError(f"duplicate QA benchmark task id: {task_id}")
        task_ids.add(task_id)

        category = raw_task.get("category")
        if not isinstance(category, str) or not _TASK_ID_RE.fullmatch(category.replace("_", "-")):
            raise QABenchmarkError(f"task {task_id} category is invalid: {category!r}")
        prompt = raw_task.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            raise QABenchmarkError(f"task {task_id} prompt must contain 1..12000 characters")
        max_tokens = raw_task.get("max_completion_tokens")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 16 <= max_tokens <= 1024
        ):
            raise QABenchmarkError(
                f"task {task_id} max_completion_tokens must be an integer from 16 through 1024"
            )
        expected = raw_task.get("expected")
        if not isinstance(expected, dict) or not expected:
            raise QABenchmarkError(f"task {task_id} expected must be a non-empty object")
        sensitive = _find_sensitive_key(expected)
        if sensitive is not None:
            raise QABenchmarkError(f"task {task_id} expected contains sensitive key: {sensitive}")
        _validate_json_value(expected, path=f"tasks[{index}].expected")

        normalized_tasks.append(
            {
                "id": task_id,
                "category": category,
                "prompt": prompt,
                "max_completion_tokens": max_tokens,
                "expected": expected,
            }
        )

    return {
        "schema_version": 1,
        "suite_id": suite_id,
        "title": title,
        "claim_boundary": boundary,
        "tasks": normalized_tasks,
    }


def get_qa_task(suite: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in suite["tasks"]:
        if task["id"] == task_id:
            return task
    raise QABenchmarkError(f"unknown QA benchmark task id: {task_id}")


def build_qa_request(*, suite: dict[str, Any], task_id: str, model: str) -> dict[str, Any]:
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
        raise QABenchmarkError(f"invalid model identifier: {model!r}")
    task = get_qa_task(suite, task_id)
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are under deterministic QA evaluation. Follow the requested JSON "
                    "contract exactly. Return no Markdown, prose, or code fences."
                ),
            },
            {"role": "user", "content": task["prompt"]},
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0,
        "max_completion_tokens": task["max_completion_tokens"],
    }


def _extract_output_text(events: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for event in events:
        if event.get("event") != "chunk":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        choices = payload.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "".join(parts)


def _same_json_type(expected: Any, observed: Any) -> bool:
    if expected is None:
        return observed is None
    if isinstance(expected, bool):
        return isinstance(observed, bool)
    if isinstance(expected, int):
        return isinstance(observed, int) and not isinstance(observed, bool)
    if isinstance(expected, float):
        return isinstance(observed, float)
    return type(expected) is type(observed)


def _structure_matches(expected: Any, observed: Any) -> bool:
    if not _same_json_type(expected, observed):
        return False
    if isinstance(expected, dict):
        return set(expected) == set(observed) and all(
            _structure_matches(expected[key], observed[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(expected) == len(observed) and all(
            _structure_matches(expected_item, observed_item)
            for expected_item, observed_item in zip(expected, observed)
        )
    return True


def _leaf_checks(expected: Any, observed: Any, *, path: str = "$") -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if isinstance(expected, dict):
        for key in expected:
            child_observed = observed.get(key) if isinstance(observed, dict) else None
            checks.extend(_leaf_checks(expected[key], child_observed, path=f"{path}.{key}"))
        return checks
    if isinstance(expected, list):
        for index, item in enumerate(expected):
            child_observed = (
                observed[index]
                if isinstance(observed, list) and index < len(observed)
                else None
            )
            checks.extend(_leaf_checks(item, child_observed, path=f"{path}[{index}]"))
        return checks

    type_match = _same_json_type(expected, observed)
    checks.append(
        {
            "path": path,
            "expected": expected,
            "observed": observed,
            "passed": type_match and observed == expected,
        }
    )
    return checks


def score_qa_capture(
    *,
    suite: dict[str, Any],
    task_id: str,
    capture_path: Path,
    provider: str,
    model: str,
) -> dict[str, Any]:
    task = get_qa_task(suite, task_id)
    events = load_capture(capture_path)
    analysis = analyze_capture(events, provider=provider, model=model)
    text = _extract_output_text(events)
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    base = {
        "schema_version": 1,
        "suite_id": suite["suite_id"],
        "task_id": task_id,
        "category": task["category"],
        "provider": provider,
        "model": model,
        "inference_status": analysis["status"],
        "http_status": analysis["http_status"],
        "output": {
            "text_characters": len(text),
            "text_sha256": text_sha256,
        },
        "claim_boundary": suite["claim_boundary"],
    }

    if analysis["status"] != "COMPLETE":
        return {
            **base,
            "status": "INFERENCE_FAILED",
            "score": {"earned": 0, "possible": 1, "percent": 0.0},
            "parse_error": analysis.get("error") or "inference did not complete",
            "checks": [],
        }

    try:
        observed = json.loads(text.strip())
    except json.JSONDecodeError as error:
        return {
            **base,
            "status": "INVALID_RESPONSE",
            "score": {"earned": 0, "possible": 1, "percent": 0.0},
            "parse_error": f"response is not strict JSON: {error.msg}",
            "checks": [],
        }
    if not isinstance(observed, dict):
        return {
            **base,
            "status": "INVALID_RESPONSE",
            "score": {"earned": 0, "possible": 1, "percent": 0.0},
            "parse_error": "response JSON must be an object",
            "checks": [],
        }
    sensitive = _find_sensitive_key(observed)
    if sensitive is not None:
        return {
            **base,
            "status": "INVALID_RESPONSE",
            "score": {"earned": 0, "possible": 1, "percent": 0.0},
            "parse_error": f"response contains a sensitive key: {sensitive}",
            "checks": [],
        }
    try:
        _validate_json_value(observed, path="response")
    except QABenchmarkError as error:
        return {
            **base,
            "status": "INVALID_RESPONSE",
            "score": {"earned": 0, "possible": 1, "percent": 0.0},
            "parse_error": str(error),
            "checks": [],
        }

    structure_passed = _structure_matches(task["expected"], observed)
    checks = [
        {
            "path": "$",
            "kind": "exact_structure",
            "passed": structure_passed,
        },
        *_leaf_checks(task["expected"], observed),
    ]
    earned = sum(1 for check in checks if check["passed"])
    possible = len(checks)
    percent = round(earned * 100.0 / possible, 6)
    return {
        **base,
        "status": "PASS" if earned == possible else "FAIL",
        "score": {"earned": earned, "possible": possible, "percent": percent},
        "parse_error": None,
        "observed": observed,
        "checks": checks,
    }


def summarize_qa_reports(
    *,
    suite: dict[str, Any],
    reports: Iterable[dict[str, Any]],
    provider: str,
    model: str,
) -> dict[str, Any]:
    expected_ids = [task["id"] for task in suite["tasks"]]
    by_id: dict[str, dict[str, Any]] = {}
    for report in reports:
        if not isinstance(report, dict):
            raise QABenchmarkError("QA task report must be an object")
        if report.get("suite_id") != suite["suite_id"]:
            raise QABenchmarkError("QA task report suite_id mismatch")
        if report.get("provider") != provider or report.get("model") != model:
            raise QABenchmarkError("QA task report provider/model mismatch")
        task_id = report.get("task_id")
        if not isinstance(task_id, str) or task_id not in expected_ids:
            raise QABenchmarkError(f"QA task report has unknown task_id: {task_id!r}")
        if task_id in by_id:
            raise QABenchmarkError(f"duplicate QA task report: {task_id}")
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
        by_id[task_id] = report

    missing = [task_id for task_id in expected_ids if task_id not in by_id]
    if missing:
        raise QABenchmarkError(f"missing QA task reports: {missing}")

    ordered = [by_id[task_id] for task_id in expected_ids]
    earned = sum(report["score"]["earned"] for report in ordered)
    possible = sum(report["score"]["possible"] for report in ordered)
    categories: dict[str, dict[str, int | float]] = {}
    for report in ordered:
        category = report["category"]
        bucket = categories.setdefault(category, {"earned": 0, "possible": 0})
        bucket["earned"] += report["score"]["earned"]
        bucket["possible"] += report["score"]["possible"]
    for bucket in categories.values():
        bucket["percent"] = round(
            bucket["earned"] * 100.0 / bucket["possible"], 6
        )

    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "suite_id": suite["suite_id"],
        "title": suite["title"],
        "provider": provider,
        "model": model,
        "tasks_total": len(ordered),
        "tasks_passed": sum(report["status"] == "PASS" for report in ordered),
        "tasks_failed": sum(report["status"] == "FAIL" for report in ordered),
        "tasks_invalid": sum(
            report["status"] in {"INVALID_RESPONSE", "INFERENCE_FAILED"}
            for report in ordered
        ),
        "score": {
            "earned": earned,
            "possible": possible,
            "percent": round(earned * 100.0 / possible, 6),
        },
        "categories": categories,
        "task_results": [
            {
                "task_id": report["task_id"],
                "category": report["category"],
                "status": report["status"],
                "score": report["score"],
                "output_sha256": report["output"]["text_sha256"],
            }
            for report in ordered
        ],
        "claim_boundary": suite["claim_boundary"],
    }
