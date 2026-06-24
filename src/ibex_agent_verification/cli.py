from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .comparator import compare_traces
from .ibex_trace import (
    load_ibex_trace,
    write_architectural_jsonl,
    write_metadata_jsonl,
    write_timing_jsonl,
)
from .models import TraceValidationError
from .silicon_gate import GateInputError, evaluate_gate
from .timing import analyze_timing, load_timing_jsonl
from .trace_io import load_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ibex-av",
        description=(
            "Parse official Ibex traces, compare architectural events, "
            "analyze timing anomalies, and gate silicon changes."
        ),
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

    ibex_trace = subparsers.add_parser(
        "parse-ibex-trace",
        help="convert trace_core_<HARTID>.log into normalized JSONL evidence",
    )
    ibex_trace.add_argument("--input", required=True, help="raw Ibex tracer log")
    ibex_trace.add_argument(
        "--output", required=True, help="architectural JSONL output path"
    )
    ibex_trace.add_argument(
        "--metadata-output",
        help="optional JSONL with cycle, decoded instruction, width, and reads",
    )
    ibex_trace.add_argument(
        "--timing-output",
        help="optional timing JSONL derived from consecutive retired cycles",
    )
    ibex_trace.add_argument(
        "--expected-cycles",
        type=int,
        default=1,
        help="baseline retirement gap used for timing output (default: 1)",
    )
    ibex_trace.add_argument("--report", help="optional parser summary JSON path")

    silicon_gate = subparsers.add_parser(
        "gate-silicon-change",
        help="issue ALLOW, BLOCK, or ESCALATE from reproducible silicon evidence",
    )
    silicon_gate.add_argument(
        "--request", required=True, help="silicon gate request JSON path"
    )
    silicon_gate.add_argument("--report", help="optional gate decision JSON path")
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
        elif args.command == "parse-ibex-trace":
            result = load_ibex_trace(args.input)
            write_architectural_jsonl(result, args.output)
            if args.metadata_output:
                write_metadata_jsonl(result, args.metadata_output)
            if args.timing_output:
                write_timing_jsonl(
                    result,
                    args.timing_output,
                    expected_cycles=args.expected_cycles,
                )
            payload = result.summary()
            payload.update(
                {
                    "architectural_output": args.output,
                    "metadata_output": args.metadata_output,
                    "timing_output": args.timing_output,
                    "expected_cycles": (
                        args.expected_cycles if args.timing_output else None
                    ),
                }
            )
            exit_code = 0
        elif args.command == "gate-silicon-change":
            payload = evaluate_gate(args.request)
            exit_code = {"ALLOW": 0, "BLOCK": 1, "ESCALATE": 3}[
                payload["decision"]
            ]
        else:
            return 2
    except (TraceValidationError, GateInputError) as exc:
        payload = {"status": "INVALID_INPUT", "error": str(exc)}
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 2

    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    _write_report(args.report, rendered)
    return exit_code
