from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cerebras_runner import (
    CerebrasRunnerBlocked,
    CerebrasRunnerError,
    run_cerebras_inference,
)
from .comparator import compare_traces
from .evidence import EvidenceError, verify_manifest
from .ibex_trace import (
    load_ibex_trace,
    write_architectural_jsonl,
    write_metadata_jsonl,
    write_timing_jsonl,
)
from .inference_evidence import InferenceEvidenceError, build_inference_bundle
from .models import TraceValidationError
from .silicon_gate import GateInputError, evaluate_gate
from .timing import analyze_timing, load_timing_jsonl
from .trace_io import load_jsonl
from .trajectory_gate import (
    TrajectoryGateError,
    evaluate_trajectory_gate_file,
)
from .transition_phase import (
    TransitionPhaseError,
    evaluate_transition_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ibex-av",
        description=(
            "Parse official Ibex traces, compare architectural events, analyze timing "
            "anomalies, verify evidence bundles and transition phases, capture inference "
            "evidence, and gate silicon changes."
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

    verify_evidence = subparsers.add_parser(
        "verify-evidence",
        help="verify every manifest-listed file and reject unlisted bundle files",
    )
    verify_evidence.add_argument(
        "--manifest", required=True, help="evidence manifest JSON path"
    )
    verify_evidence.add_argument(
        "--evidence-dir",
        help="bundle root; defaults to the manifest parent directory",
    )
    verify_evidence.add_argument(
        "--report",
        help="optional verification report outside the evidence directory",
    )

    transition_phase = subparsers.add_parser(
        "verify-transition-phase",
        help="verify one explicit transition across time, intention, and space",
    )
    transition_phase.add_argument(
        "--record",
        required=True,
        help="transition phase JSON record",
    )
    transition_phase.add_argument(
        "--report",
        help="optional transition verification report path",
    )

    trajectory_gate = subparsers.add_parser(
        "evaluate-trajectory-gate",
        help="evaluate a multi-review PR state into a fail-closed transition decision",
    )
    trajectory_gate.add_argument(
        "--record",
        required=True,
        help="normalized trajectory gate JSON record",
    )
    trajectory_gate.add_argument(
        "--report",
        help="optional trajectory gate report path",
    )

    inference_evidence = subparsers.add_parser(
        "build-inference-evidence",
        help="build a verified bundle from a recorded OpenAI-compatible stream",
    )
    inference_evidence.add_argument(
        "--request", required=True, help="sanitized OpenAI-compatible request JSON"
    )
    inference_evidence.add_argument(
        "--capture", required=True, help="timestamped inference capture JSONL"
    )
    inference_evidence.add_argument(
        "--evidence-dir", required=True, help="empty or absent bundle output directory"
    )
    inference_evidence.add_argument(
        "--provider", required=True, help="provider label, for example cerebras"
    )
    inference_evidence.add_argument("--model", required=True, help="model identifier")
    inference_evidence.add_argument(
        "--project-sha", required=True, help="repository commit producing the bundle"
    )
    inference_evidence.add_argument(
        "--report", help="optional CLI report outside the evidence directory"
    )

    cerebras_runner = subparsers.add_parser(
        "run-cerebras-inference",
        help="run one real Cerebras Cloud stream and build a verified evidence bundle",
    )
    cerebras_runner.add_argument(
        "--request", required=True, help="sanitized streaming chat request JSON"
    )
    cerebras_runner.add_argument(
        "--evidence-dir", required=True, help="empty or absent bundle output directory"
    )
    cerebras_runner.add_argument("--model", required=True, help="model identifier")
    cerebras_runner.add_argument(
        "--project-sha", required=True, help="repository commit producing the bundle"
    )
    cerebras_runner.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="single-request timeout in seconds (default: 60)",
    )
    cerebras_runner.add_argument(
        "--report", help="optional CLI report outside the Cerebras evidence directory"
    )

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
        elif args.command == "verify-evidence":
            manifest = Path(args.manifest)
            evidence_dir = Path(args.evidence_dir) if args.evidence_dir else manifest.parent
            evidence_root = evidence_dir.resolve(strict=True)
            if args.report:
                report = Path(args.report).resolve(strict=False)
                if report.is_relative_to(evidence_root):
                    raise EvidenceError(
                        "verification report must be outside the evidence directory"
                    )
            payload = verify_manifest(
                evidence_dir=evidence_dir,
                manifest_path=manifest,
            )
            exit_code = 0 if payload["status"] == "VERIFIED" else 1
        elif args.command == "verify-transition-phase":
            record_path = Path(args.record).resolve(strict=True)
            if args.report:
                report_path = Path(args.report).resolve(strict=False)
                if report_path == record_path or (
                    report_path.exists() and report_path.samefile(record_path)
                ):
                    raise TransitionPhaseError(
                        "transition verification report must differ from the source record"
                    )
            payload = evaluate_transition_file(record_path)
            exit_code = {
                "VERIFIED": 0,
                "IN_PROGRESS": 1,
                "RECALIBRATE": 3,
            }[payload["status"]]
        elif args.command == "evaluate-trajectory-gate":
            record_path = Path(args.record).resolve(strict=True)
            if args.report:
                report_path = Path(args.report).resolve(strict=False)
                if report_path == record_path or (
                    report_path.exists() and report_path.samefile(record_path)
                ):
                    raise TrajectoryGateError(
                        "trajectory gate report must differ from the source record"
                    )
            payload = evaluate_trajectory_gate_file(record_path)
            exit_code = {
                "ALLOW": 0,
                "BLOCK": 1,
                "REPAIR": 3,
                "SPLIT": 3,
                "DEFER": 3,
                "ROLLBACK": 4,
            }[payload["decision"]]
        elif args.command == "build-inference-evidence":
            evidence_dir = Path(args.evidence_dir)
            evidence_root = evidence_dir.resolve(strict=False)
            if args.report:
                report = Path(args.report).resolve(strict=False)
                if report.is_relative_to(evidence_root):
                    raise InferenceEvidenceError(
                        "CLI report must be outside the inference evidence directory"
                    )
            payload = build_inference_bundle(
                capture_path=Path(args.capture),
                request_path=Path(args.request),
                evidence_dir=evidence_dir,
                provider=args.provider,
                model=args.model,
                project_sha=args.project_sha,
            )
            exit_code = 0 if payload["result"]["status"] == "COMPLETE" else 1
        elif args.command == "run-cerebras-inference":
            evidence_dir = Path(args.evidence_dir)
            evidence_root = evidence_dir.resolve(strict=False)
            if args.report:
                report = Path(args.report).resolve(strict=False)
                if report.is_relative_to(evidence_root):
                    raise CerebrasRunnerError(
                        "CLI report must be outside the Cerebras evidence directory"
                    )
            payload = run_cerebras_inference(
                request_path=Path(args.request),
                evidence_dir=evidence_dir,
                model=args.model,
                project_sha=args.project_sha,
                timeout_seconds=args.timeout_seconds,
            )
            exit_code = 0 if payload["result"]["status"] == "COMPLETE" else 1
        elif args.command == "gate-silicon-change":
            payload = evaluate_gate(args.request)
            exit_code = {"ALLOW": 0, "BLOCK": 1, "ESCALATE": 3}[
                payload["decision"]
            ]
        else:
            return 2
    except CerebrasRunnerBlocked as exc:
        payload = {"status": "BLOCKED", "error": str(exc)}
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 4
    except (
        TraceValidationError,
        GateInputError,
        EvidenceError,
        InferenceEvidenceError,
        TransitionPhaseError,
        TrajectoryGateError,
        CerebrasRunnerError,
        OSError,
    ) as exc:
        payload = {"status": "INVALID_INPUT", "error": str(exc)}
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 2

    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    _write_report(args.report, rendered)
    return exit_code
