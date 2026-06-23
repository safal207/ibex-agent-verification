from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .comparator import compare_traces
from .models import TraceValidationError
from .trace_io import load_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ibex-av",
        description="Deterministically compare normalized Ibex execution traces.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare", help="compare two JSONL traces")
    compare.add_argument("--expected", required=True, help="expected/oracle JSONL trace")
    compare.add_argument("--actual", required=True, help="actual/DUT JSONL trace")
    compare.add_argument("--report", help="optional JSON report output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "compare":
        return 2

    try:
        expected = load_jsonl(args.expected)
        actual = load_jsonl(args.actual)
        result = compare_traces(expected, actual)
    except TraceValidationError as exc:
        payload = {"status": "INVALID_INPUT", "error": str(exc)}
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 2

    payload = result.to_dict()
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)

    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")

    return 0 if result.matches else 1
