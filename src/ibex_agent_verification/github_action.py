from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .silicon_gate import GateInputError, evaluate_gate, write_report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_output(key: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    if "\n" in key or "\r" in key or "\n" in value or "\r" in value:
        raise GateInputError("GitHub Action outputs must be single-line values")
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def _append_summary(report: dict[str, Any], report_path: Path, report_sha256: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return

    reasons = report.get("reasons", [])
    metrics = report.get("metrics", {})
    checks = report.get("checks", {})

    lines = [
        "## Silicon Evidence Gate",
        "",
        f"**Decision:** `{report['decision']}`",
        "",
        f"- Request: `{report['request_id']}`",
        f"- Report: `{report_path.as_posix()}`",
        f"- Report SHA-256: `{report_sha256}`",
        f"- Architectural trace: `{checks.get('architectural_trace', 'UNKNOWN')}`",
        f"- Evidence commit bound: `{checks.get('evidence_commit_bound', False)}`",
        "",
        "### Regression metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| New unknown timing anomalies | {metrics.get('new_unknown_delay_anomalies', 0)} |",
        f"| New explained timing anomalies | {metrics.get('new_explained_delay_anomalies', 0)} |",
        f"| New delayed redirects | {metrics.get('new_delayed_redirects', 0)} |",
        "",
        "### Reasons",
        "",
        "| Severity | Code | Message |",
        "|---|---|---|",
    ]
    for reason in reasons:
        severity = str(reason.get("severity", ""))
        code = str(reason.get("code", ""))
        message = str(reason.get("message", "")).replace("|", "\\|")
        lines.append(f"| {severity} | `{code}` | {message} |")
    lines.append("")

    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _annotation(decision: str, reason_codes: list[str]) -> str:
    joined = ", ".join(reason_codes) if reason_codes else "NO_REASON_CODE"
    if decision == "ALLOW":
        return f"::notice title=Silicon Evidence Gate::ALLOW — {joined}"
    if decision == "ESCALATE":
        return f"::warning title=Silicon Evidence Gate::ESCALATE — {joined}"
    return f"::error title=Silicon Evidence Gate::BLOCK — {joined}"


def run(request: str | Path, report: str | Path) -> dict[str, Any]:
    report_path = Path(report)
    gate_report = evaluate_gate(request)
    write_report(gate_report, report_path)
    report_sha256 = _sha256(report_path)
    reason_codes = [str(item.get("code", "")) for item in gate_report["reasons"]]

    _append_output("decision", gate_report["decision"])
    _append_output("reason_codes", ",".join(reason_codes))
    _append_output("request_sha256", gate_report["request_sha256"])
    _append_output("report_sha256", report_sha256)
    _append_output("report_path", report_path.as_posix())
    _append_summary(gate_report, report_path, report_sha256)
    print(_annotation(gate_report["decision"], reason_codes))
    print(json.dumps(gate_report, indent=2, sort_keys=True))
    return gate_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Silicon Evidence Gate and publish GitHub Action outputs."
    )
    parser.add_argument("--request", required=True, help="gate request JSON path")
    parser.add_argument("--report", required=True, help="gate report JSON path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args.request, args.report)
    except GateInputError as exc:
        print(f"::error title=Silicon Evidence Gate::INVALID_INPUT — {exc}")
        print(json.dumps({"status": "INVALID_INPUT", "error": str(exc)}, indent=2))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
