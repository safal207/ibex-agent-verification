#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ibex_agent_verification.inference_evidence import (
    InferenceEvidenceError,
    load_capture,
)
from ibex_agent_verification.qa_benchmark import (
    QABenchmarkError,
    build_qa_request,
    get_qa_task,
    load_qa_suite,
    score_qa_capture,
    summarize_qa_reports,
)


def _write_json(path: Path, payload: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_report(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise QABenchmarkError(f"QA task report must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise QABenchmarkError(f"{path}: invalid QA task report JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise QABenchmarkError(f"QA task report must be an object: {path}")
    return payload


def _finish_reasons(capture_path: Path) -> list[str]:
    reasons: list[str] = []
    for event in load_capture(capture_path):
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
            reason = choice.get("finish_reason")
            if isinstance(reason, str) and reason and reason not in reasons:
                reasons.append(reason)
    return reasons


def _annotate_completion_budget(
    payload: dict,
    *,
    capture_path: Path,
    max_completion_tokens: int,
) -> dict:
    reasons = _finish_reasons(capture_path)
    payload["finish_reasons"] = reasons
    if "length" not in reasons:
        return payload

    payload["status"] = "OUTPUT_TRUNCATED"
    payload["score"] = {"earned": 0, "possible": 1, "percent": 0.0}
    payload["parse_error"] = (
        "provider ended the completion with finish_reason=length before a complete "
        "strict-JSON answer was available"
    )
    payload["checks"] = []
    payload.pop("observed", None)
    payload["diagnostic"] = {
        "code": "OUTPUT_TRUNCATED",
        "finish_reason": "length",
        "max_completion_tokens": max_completion_tokens,
        "classification": "benchmark_configuration_or_model_budget_limit",
    }
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare, score, and summarize deterministic AI QA benchmark evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--suite", required=True, type=Path)
    prepare.add_argument("--task-id", required=True)
    prepare.add_argument("--model", required=True)
    prepare.add_argument("--output", required=True, type=Path)

    score = subparsers.add_parser("score")
    score.add_argument("--suite", required=True, type=Path)
    score.add_argument("--task-id", required=True)
    score.add_argument("--capture", required=True, type=Path)
    score.add_argument("--provider", required=True)
    score.add_argument("--model", required=True)
    score.add_argument("--report", required=True, type=Path)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--suite", required=True, type=Path)
    summarize.add_argument("--reports-dir", required=True, type=Path)
    summarize.add_argument("--provider", required=True)
    summarize.add_argument("--model", required=True)
    summarize.add_argument("--report", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        suite = load_qa_suite(args.suite)
        if args.command == "prepare":
            payload = build_qa_request(
                suite=suite,
                task_id=args.task_id,
                model=args.model,
            )
            _write_json(args.output, payload)
        elif args.command == "score":
            task = get_qa_task(suite, args.task_id)
            payload = score_qa_capture(
                suite=suite,
                task_id=args.task_id,
                capture_path=args.capture,
                provider=args.provider,
                model=args.model,
            )
            payload = _annotate_completion_budget(
                payload,
                capture_path=args.capture,
                max_completion_tokens=task["max_completion_tokens"],
            )
            _write_json(args.report, payload)
        elif args.command == "summarize":
            reports_dir = args.reports_dir.resolve()
            if reports_dir.is_symlink() or not reports_dir.is_dir():
                raise QABenchmarkError(
                    f"QA reports directory must be a real directory: {reports_dir}"
                )
            expected_names = {f"{task['id']}.json" for task in suite["tasks"]}
            observed_names = {
                path.name for path in reports_dir.iterdir() if path.is_file()
            }
            if observed_names != expected_names:
                raise QABenchmarkError(
                    "QA reports directory must contain exactly the expected task reports; "
                    f"expected={sorted(expected_names)} observed={sorted(observed_names)}"
                )
            reports = [
                _read_report(reports_dir / f"{task['id']}.json")
                for task in suite["tasks"]
            ]
            payload = summarize_qa_reports(
                suite=suite,
                reports=reports,
                provider=args.provider,
                model=args.model,
            )
            truncated = sum(
                report.get("status") == "OUTPUT_TRUNCATED" for report in reports
            )
            payload["tasks_truncated"] = truncated
            payload["tasks_invalid"] = sum(
                report.get("status")
                in {"INVALID_RESPONSE", "INFERENCE_FAILED", "OUTPUT_TRUNCATED"}
                for report in reports
            )
            _write_json(args.report, payload)
        else:
            return 2
    except (OSError, QABenchmarkError, InferenceEvidenceError) as error:
        print(f"QA benchmark error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
