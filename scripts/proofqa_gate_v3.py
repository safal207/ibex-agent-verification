#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ProofQAGateV3Error(ValueError):
    """Raised when scorecard v2/v3 evidence or release policy is invalid."""


@dataclass(frozen=True)
class GatePolicyV3:
    min_end_to_end: float
    min_answer_correctness: float
    min_completion_reliability: float
    min_provider_reliability: float
    warn_margin: float
    max_p95_duration_ms: float
    time_warn_margin_ms: float
    unknown_metric_policy: str
    fail_on: str
    policy_name: str


_PERCENT_AXES = (
    ("end_to_end", "End-to-end score", "end_to_end_score", "min_end_to_end"),
    (
        "answer_correctness",
        "Answer correctness",
        "answer_correctness",
        "min_answer_correctness",
    ),
    (
        "completion_reliability",
        "Completion reliability",
        "completion_reliability",
        "min_completion_reliability",
    ),
    (
        "provider_reliability",
        "Provider reliability",
        "provider_reliability",
        "min_provider_reliability",
    ),
)
_DECISION_ORDER = {"PASS": 0, "WARN": 1, "BLOCK": 2}


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProofQAGateV3Error(f"{label} must be a regular non-symlink file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProofQAGateV3Error(f"{path}: invalid {label} JSON: {error.msg}") from error
    except OSError as error:
        raise ProofQAGateV3Error(f"cannot read {label} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ProofQAGateV3Error(f"{label} must be a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_number(
    value: str,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ProofQAGateV3Error(
            f"{name} must be a number from {minimum:g} through {maximum:g}"
        ) from error
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise ProofQAGateV3Error(
            f"{name} must be a finite number from {minimum:g} through {maximum:g}"
        )
    return parsed


def _parse_percent(value: str, *, name: str) -> float:
    return _parse_number(value, name=name, minimum=0.0, maximum=100.0)


def _require_choice(value: str, *, name: str, choices: set[str]) -> str:
    normalized = value.strip().lower()
    if normalized not in choices:
        raise ProofQAGateV3Error(
            f"{name} must be one of {sorted(choices)}, observed {value!r}"
        )
    return normalized


def policy_from_environment(environment: Mapping[str, str]) -> GatePolicyV3:
    policy_name = environment.get("PROOFQA_POLICY_NAME", "default").strip()
    if not policy_name or len(policy_name) > 120:
        raise ProofQAGateV3Error(
            "policy-name must contain from 1 through 120 characters"
        )
    return GatePolicyV3(
        min_end_to_end=_parse_percent(
            environment.get("PROOFQA_MIN_END_TO_END", "90"),
            name="min-end-to-end",
        ),
        min_answer_correctness=_parse_percent(
            environment.get("PROOFQA_MIN_ANSWER_CORRECTNESS", "90"),
            name="min-answer-correctness",
        ),
        min_completion_reliability=_parse_percent(
            environment.get("PROOFQA_MIN_COMPLETION_RELIABILITY", "95"),
            name="min-completion-reliability",
        ),
        min_provider_reliability=_parse_percent(
            environment.get("PROOFQA_MIN_PROVIDER_RELIABILITY", "95"),
            name="min-provider-reliability",
        ),
        warn_margin=_parse_percent(
            environment.get("PROOFQA_WARN_MARGIN", "3"),
            name="warn-margin",
        ),
        max_p95_duration_ms=_parse_number(
            environment.get("PROOFQA_MAX_P95_DURATION_MS", "0"),
            name="max-p95-duration-ms",
            minimum=0.0,
            maximum=3_600_000.0,
        ),
        time_warn_margin_ms=_parse_number(
            environment.get("PROOFQA_TIME_WARN_MARGIN_MS", "250"),
            name="time-warn-margin-ms",
            minimum=0.0,
            maximum=3_600_000.0,
        ),
        unknown_metric_policy=_require_choice(
            environment.get("PROOFQA_UNKNOWN_METRIC_POLICY", "block"),
            name="unknown-metric-policy",
            choices={"block", "warn", "ignore"},
        ),
        fail_on=_require_choice(
            environment.get("PROOFQA_FAIL_ON", "block"),
            name="fail-on",
            choices={"block", "warn", "never"},
        ),
        policy_name=policy_name,
    )


def _finite_metric(value: Any, *, label: str, maximum: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofQAGateV3Error(f"{label} must be a number or null")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 <= parsed <= maximum:
        raise ProofQAGateV3Error(f"{label} must be from 0 through {maximum:g}")
    return parsed


def _metric_percent(scorecard: dict[str, Any], section_name: str) -> float | None:
    section = scorecard.get(section_name)
    if not isinstance(section, dict):
        raise ProofQAGateV3Error(f"scorecard.{section_name} must be an object")
    return _finite_metric(
        section.get("percent"),
        label=f"scorecard.{section_name}.percent",
        maximum=100.0,
    )


def _p95_duration(scorecard: dict[str, Any], *, scorecard_version: int) -> float | None:
    if scorecard_version == 2:
        return None
    time_performance = scorecard.get("time_performance")
    if not isinstance(time_performance, dict):
        raise ProofQAGateV3Error("scorecard.time_performance must be an object")
    successful = time_performance.get("successful_requests")
    if not isinstance(successful, dict):
        raise ProofQAGateV3Error(
            "scorecard.time_performance.successful_requests must be an object"
        )
    duration = successful.get("duration_ms")
    if not isinstance(duration, dict):
        raise ProofQAGateV3Error(
            "scorecard.time_performance.successful_requests.duration_ms must be an object"
        )
    return _finite_metric(
        duration.get("p95"),
        label="scorecard.time_performance.successful_requests.duration_ms.p95",
        maximum=3_600_000.0,
    )


def validate_summary(summary: dict[str, Any]) -> dict[str, float | None]:
    scorecard_version = summary.get("scorecard_version")
    if scorecard_version not in {2, 3}:
        raise ProofQAGateV3Error(
            "summary scorecard_version must equal 2 or 3; legacy or unknown scorecards fail closed"
        )
    scorecard = summary.get("scorecard")
    if not isinstance(scorecard, dict):
        raise ProofQAGateV3Error("summary.scorecard must be an object")
    expected_schema = 1 if scorecard_version == 2 else 2
    if scorecard.get("schema_version") != expected_schema:
        raise ProofQAGateV3Error(
            f"summary.scorecard.schema_version must equal {expected_schema} for scorecard v{scorecard_version}"
        )

    metrics: dict[str, float | None] = {}
    for key, _label, section_name, _policy_field in _PERCENT_AXES:
        metrics[key] = _metric_percent(scorecard, section_name)
    metrics["p95_duration_ms"] = _p95_duration(
        scorecard,
        scorecard_version=scorecard_version,
    )

    for field in ("suite_id", "provider", "model"):
        value = summary.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProofQAGateV3Error(f"summary.{field} must be a non-empty string")
    return metrics


def _max_decision(first: str, second: str) -> str:
    return first if _DECISION_ORDER[first] >= _DECISION_ORDER[second] else second


def _unknown_status(policy: GatePolicyV3) -> str:
    return {
        "block": "BLOCK",
        "warn": "WARN",
        "ignore": "PASS",
    }[policy.unknown_metric_policy]


def evaluate_gate(
    *,
    summary: dict[str, Any],
    policy: GatePolicyV3,
) -> dict[str, Any]:
    metrics = validate_summary(summary)
    decision = "PASS"
    findings: list[dict[str, Any]] = []

    for key, label, _section_name, policy_field in _PERCENT_AXES:
        actual = metrics[key]
        minimum = float(getattr(policy, policy_field))
        warn_below = min(100.0, minimum + policy.warn_margin)

        if actual is None:
            status = _unknown_status(policy)
            message = (
                f"{label} is unavailable; unknown-metric-policy="
                f"{policy.unknown_metric_policy}"
            )
        elif actual < minimum:
            status = "BLOCK"
            message = f"{label} {actual:.6f}% is below minimum {minimum:.6f}%"
        elif policy.warn_margin > 0 and actual < warn_below:
            status = "WARN"
            message = (
                f"{label} {actual:.6f}% passes minimum {minimum:.6f}% "
                f"but is inside the {policy.warn_margin:.6f}-point warning margin"
            )
        else:
            status = "PASS"
            message = (
                f"{label} {actual:.6f}% satisfies the policy"
                if actual is not None
                else f"{label} is unavailable and ignored"
            )

        decision = _max_decision(decision, status)
        findings.append(
            {
                "axis": key,
                "label": label,
                "direction": "minimum",
                "actual": actual,
                "unit": "percent",
                "threshold": minimum,
                "warning_boundary": warn_below,
                "enabled": True,
                "status": status,
                "message": message,
            }
        )

    time_actual = metrics["p95_duration_ms"]
    if policy.max_p95_duration_ms == 0:
        time_status = "PASS"
        time_message = "Successful-request p95 time SLO is disabled by policy"
        time_enabled = False
        warning_boundary = None
    elif time_actual is None:
        time_status = _unknown_status(policy)
        time_message = (
            "Successful-request p95 duration is unavailable; unknown-metric-policy="
            f"{policy.unknown_metric_policy}"
        )
        time_enabled = True
        warning_boundary = max(
            0.0,
            policy.max_p95_duration_ms - policy.time_warn_margin_ms,
        )
    else:
        time_enabled = True
        warning_boundary = max(
            0.0,
            policy.max_p95_duration_ms - policy.time_warn_margin_ms,
        )
        if time_actual > policy.max_p95_duration_ms:
            time_status = "BLOCK"
            time_message = (
                f"Successful-request p95 duration {time_actual:.6f} ms exceeds maximum "
                f"{policy.max_p95_duration_ms:.6f} ms"
            )
        elif (
            policy.time_warn_margin_ms > 0
            and time_actual > warning_boundary
        ):
            time_status = "WARN"
            time_message = (
                f"Successful-request p95 duration {time_actual:.6f} ms meets the maximum "
                f"{policy.max_p95_duration_ms:.6f} ms but is inside the "
                f"{policy.time_warn_margin_ms:.6f} ms warning margin"
            )
        else:
            time_status = "PASS"
            time_message = (
                f"Successful-request p95 duration {time_actual:.6f} ms satisfies the policy"
            )

    decision = _max_decision(decision, time_status)
    findings.append(
        {
            "axis": "time_performance",
            "label": "Successful-request p95 duration",
            "direction": "maximum",
            "actual": time_actual,
            "unit": "milliseconds",
            "threshold": policy.max_p95_duration_ms,
            "warning_boundary": warning_boundary,
            "enabled": time_enabled,
            "status": time_status,
            "message": time_message,
        }
    )

    should_fail = (
        policy.fail_on == "warn" and decision in {"WARN", "BLOCK"}
    ) or (policy.fail_on == "block" and decision == "BLOCK")
    return {
        "decision": decision,
        "should_fail": should_fail,
        "metrics": metrics,
        "findings": findings,
    }


def build_report(
    *,
    summary_path: Path,
    summary: dict[str, Any],
    policy: GatePolicyV3,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "product": "ProofQA Release Gate",
        "decision": evaluation["decision"],
        "should_fail": evaluation["should_fail"],
        "source": {
            "summary_path": str(summary_path),
            "summary_sha256": _sha256(summary_path),
            "suite_id": summary["suite_id"],
            "provider": summary["provider"],
            "model": summary["model"],
            "scorecard_version": summary["scorecard_version"],
        },
        "policy": {
            "name": policy.policy_name,
            "min_end_to_end": policy.min_end_to_end,
            "min_answer_correctness": policy.min_answer_correctness,
            "min_completion_reliability": policy.min_completion_reliability,
            "min_provider_reliability": policy.min_provider_reliability,
            "warn_margin": policy.warn_margin,
            "max_p95_duration_ms": policy.max_p95_duration_ms,
            "time_warn_margin_ms": policy.time_warn_margin_ms,
            "unknown_metric_policy": policy.unknown_metric_policy,
            "fail_on": policy.fail_on,
        },
        "metrics": evaluation["metrics"],
        "findings": evaluation["findings"],
        "claim_boundary": (
            "The gate applies configured correctness, reliability, and time thresholds to one "
            "ProofQA scorecard. It does not establish stable model quality or latency without "
            "repeated, versioned evidence."
        ),
    }


def _display(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}%" if unit == "percent" else f"{value:.6f} ms"


def _output_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}"


def render_markdown(report: dict[str, Any]) -> str:
    icon = {"PASS": "✅", "WARN": "⚠️", "BLOCK": "🛑"}[report["decision"]]
    policy = report["policy"]
    source = report["source"]
    lines = [
        f"## {icon} ProofQA Release Gate — {report['decision']}",
        "",
        f"- Policy: `{policy['name']}`",
        f"- Suite: `{source['suite_id']}`",
        f"- Provider/model: `{source['provider']}` / `{source['model']}`",
        f"- Scorecard: `v{source['scorecard_version']}`",
        f"- Summary SHA-256: `{source['summary_sha256']}`",
        f"- Enforcement: `fail-on={policy['fail_on']}`",
        "",
        "| Axis | Actual | Policy | Result |",
        "|---|---:|---:|---|",
    ]
    for finding in report["findings"]:
        if not finding["enabled"]:
            policy_text = "disabled"
        elif finding["direction"] == "minimum":
            policy_text = f">= {finding['threshold']:.6f}%"
        else:
            policy_text = f"<= {finding['threshold']:.6f} ms"
        lines.append(
            f"| {finding['label']} | {_display(finding['actual'], finding['unit'])} | "
            f"{policy_text} | `{finding['status']}` |"
        )
    lines.extend(["", "### Findings", ""])
    for finding in report["findings"]:
        lines.append(f"- **{finding['status']}** — {finding['message']}")
    lines.extend(["", f"Boundary: {report['claim_boundary']}", ""])
    return "\n".join(lines)


def _escape_workflow_command(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _write_outputs(path: Path, report: dict[str, Any], report_path: Path) -> None:
    metrics = report["metrics"]
    values = {
        "decision": report["decision"],
        "should-fail": str(report["should_fail"]).lower(),
        "report-path": str(report_path),
        "summary-sha256": report["source"]["summary_sha256"],
        "end-to-end-percent": _output_number(metrics["end_to_end"]),
        "answer-correctness-percent": _output_number(metrics["answer_correctness"]),
        "completion-reliability-percent": _output_number(
            metrics["completion_reliability"]
        ),
        "provider-reliability-percent": _output_number(
            metrics["provider_reliability"]
        ),
        "p95-duration-ms": _output_number(metrics["p95_duration_ms"]),
    }
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def run(environment: Mapping[str, str]) -> int:
    summary_raw = environment.get("PROOFQA_SUMMARY_PATH", "").strip()
    if not summary_raw:
        raise ProofQAGateV3Error("summary-path is required")
    report_raw = environment.get(
        "PROOFQA_REPORT_PATH", "proofqa-gate-report.json"
    ).strip()
    if not report_raw:
        raise ProofQAGateV3Error("report-path must not be empty")

    summary_path = Path(summary_raw)
    report_path = Path(report_raw)
    if report_path.is_symlink() or report_path.is_dir():
        raise ProofQAGateV3Error(
            f"report-path must be a writable regular-file path: {report_path}"
        )

    summary = _load_json_object(summary_path, label="ProofQA summary")
    summary_resolved = summary_path.resolve(strict=True)
    report_resolved = report_path.resolve(strict=False)
    same_existing_file = report_path.exists() and os.path.samefile(
        summary_resolved, report_path
    )
    if report_resolved == summary_resolved or same_existing_file:
        raise ProofQAGateV3Error("report-path must differ from summary-path")

    policy = policy_from_environment(environment)
    evaluation = evaluate_gate(summary=summary, policy=policy)
    report = build_report(
        summary_path=summary_path,
        summary=summary,
        policy=policy,
        evaluation=evaluation,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown = render_markdown(report)
    print(markdown)

    step_summary = environment.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8", newline="\n") as output:
            output.write(markdown)

    github_output = environment.get("GITHUB_OUTPUT")
    if github_output:
        _write_outputs(Path(github_output), report, report_path)

    annotation = "error" if report["decision"] == "BLOCK" else "warning"
    if report["decision"] != "PASS":
        messages = "; ".join(
            finding["message"]
            for finding in report["findings"]
            if finding["status"] != "PASS"
        )
        print(
            f"::{annotation} title=ProofQA {report['decision']}::"
            f"{_escape_workflow_command(messages)}"
        )

    return 1 if report["should_fail"] else 0


def main() -> int:
    try:
        return run(os.environ)
    except (OSError, ProofQAGateV3Error) as error:
        message = _escape_workflow_command(str(error))
        print(f"::error title=ProofQA configuration error::{message}")
        print(f"ProofQA gate error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
