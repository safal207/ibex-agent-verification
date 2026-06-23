from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .comparator import compare_traces
from .models import TraceValidationError
from .timing import analyze_timing, load_timing_jsonl
from .trace_io import load_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ibex-av",
        description="Deterministically compare Ibex traces and analyze timing anomalies.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare", help="compare two JSONL traces")
    compare.add_argument("--expected", required=True, help="expected/oracle JSONL trace")
    compare.add_argument("--actual", required=True, help="actual/DUT JSONL trace")
    compare.add_argument("--report", help="optional JSON report output path")

    timing = subparsers.add_parser(
        "analyze-timing",
        help="analyze cycle deviations and rank evidence-backed root causes",
    )
    timing.add_argument("--input", required=True, help="timing JSONL input")
    timing.add_argument("--report", help="optional JSON report output path")
    return parser


def _write_report(path: str | None, rendered: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "compare":
            expected = load_jsonl(args.expected)
            actual = load_jsonl(args.actual)
            result = compare_traces(expected, actual)
            payload = result.to_dict()
            exit_code = 0 if result.matches else 1
        elif args.command == "analyze-timing":
            result = analyze_timing(load_timing_jsonl(args.input))
            payload = result.to_dict()
            exit_code = 1 if result.has_anomalies else 0
        else:
            return 2
    except TraceValidationError as exc:
        payload = {"status": "INVALID_INPUT", "error": str(exc)}
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 2

    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    _write_report(args.report, rendered)
    return exit_code
