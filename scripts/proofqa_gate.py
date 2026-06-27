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


class ProofQAGateError(ValueError):
    """Raised when the gate policy or scorecard input is malformed."""


@dataclass(frozen=True)
class GatePolicy:
    min_end_to_end: float
    min_answer_correctness: float
    min_completion_reliability: float
    min_provider_reliability: float
    warn_margin: float
    unknown_metric_policy: str
    fail_on: str
    policy_name: str


_AXIS_SPECS = (
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
        raise ProofQAGateError(f"{label} must be a regular non-symlink file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProofQAGateError(f"{path}: invalid {label} JSON: {error.msg}") from error
    except OSError as error:
        raise ProofQAGateError(f"cannot read {label} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ProofQAGateError(f"{label} must be a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_percent(value: str, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ProofQAGateError(f"{name} must be a number from 0 through 100") from error
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 100.0:
        raise ProofQAGateError(f"{name} must be a finite number from 0 through 100")
    return parsed


def _require_choice(value: str, *, name: str, choices: set[str]) -> str:
    normalized = value.strip().lower()
    if normalized not in choices:
        raise ProofQAGateError(
            f"{name} must be one of {sorted(choices)}, observed {value!r}"
        )
    return normalized


def policy_from_environment(environment: Mapping[str, str]) -> GatePolicy:
    policy_name = environment.get("PROOFQA_POLICY_NAME", "default").strip()
    if not policy_name or len(policy_name) > 120:
        raise ProofQAGateError("policy-name must contain from 1 through 120 characters")
    return GatePolicy(
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


def _metric_percent(scorecard: dict[str, Any], section_name: str) -> float | None:
    section = scorecard.get(section_name)
    if not isinstance(section, dict):
        raise ProofQAGateError(f"scorecard.{section_name} must be an object")
    value = section.get("percent")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofQAGateError(
            f"scorecard.{section_name}.percent must be a number or null"
        )
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 100.0:
        raise ProofQAGateError(
            f"scorecard.{section_name}.percent must be from 0 through 100"
        )
    return parsed


def validate_summary(summary: dict[str, Any]) -> dict[str, float | None]:
    if summary.get("scorecard_version") != 2:
        raise ProofQAGateError(
            "summary scorecard_version must equal 2; legacy or unknown scorecards fail closed"
        )
    scorecard = summary.get("scorecard")
    if not isinstance(scorecard, dict):
        raise ProofQAGateError("summary.scorecard must be an object")
    if scorecard.get("schema_version") != 1:
        raise ProofQAGateError("summary.scorecard.schema_version must equal 1")

    metrics: dict[str, float | None] = {}
    for key, _label, section_name, _policy_field in _AXIS_SPECS:
        metrics[key] = _metric_percent(scorecard, section_name)

    for field in ("suite_id", "provider", "model"):
        value = summary.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProofQAGateError(f"summary.{field} must be a non-empty string")
    return metrics


def _max_decision(first: str, second: str) -> str:
    return first if _DECISION_ORDER[first] >= _DECISION_ORDER[second] else second


def evaluate_gate(
    *,
    summary: dict[str, Any],
    policy: GatePolicy,
) -> dict[str, Any]:
    metrics = validate_summary(summary)
    decision = "PASS"
    findings: list[dict[str, Any]] = []

    for key, label, _section_name, policy_field in _AXIS_SPECS:
        actual = metrics[key]
        minimum = float(getattr(policy, policy_field))
        warn_below = min(100.0, minimum + policy.warn_margin)

        if actual is None:
            if policy.unknown_metric_policy == "block":
                status = "BLOCK"
            elif policy.unknown_metric_policy == "warn":
                status = "WARN"
            else:
                status = "PASS"
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
            if actual is None:
                message = (
                    f"{label} is unavailable and ignored by unknown-metric-policy=ignore"
                )
            else:
                message = f"{label} {actual:.6f}% satisfies the policy"

        decision = _max_decision(decision, status)
        findings.append(
            {
                "axis": key,
                "label": label,
                "actual_percent": actual,
                "minimum_percent": minimum,
                "warn_below_percent": warn_below,
                "status": status,
                "message": message,
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
    policy: GatePolicy,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
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
            "unknown_metric_policy": policy.unknown_metric_policy,
            "fail_on": policy.fail_on,
        },
        "metrics": evaluation["metrics"],
        "findings": evaluation["findings"],
        "claim_boundary": (
            "The gate applies configured thresholds to one ProofQA scorecard. It does not "
            "establish stable model quality without repeated, versioned evidence."
        ),
    }


def _display_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}%"


def _output_percent(value: float | None) -> str:
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
        f"- Summary SHA-256: `{source['summary_sha256']}`",
        f"- Enforcement: `fail-on={policy['fail_on']}`",
        "",
        "| Axis | Actual | Minimum | Result |",
        "|---|---:|---:|---|",
    ]
    for finding in report["findings"]:
        lines.append(
            f"| {finding['label']} | {_display_percent(finding['actual_percent'])} | "
            f"{finding['minimum_percent']:.6f}% | `{finding['status']}` |"
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
        "end-to-end-percent": _output_percent(metrics["end_to_end"]),
        "answer-correctness-percent": _output_percent(metrics["answer_correctness"]),
        "completion-reliability-percent": _output_percent(
            metrics["completion_reliability"]
        ),
        "provider-reliability-percent": _output_percent(
            metrics["provider_reliability"]
        ),
    }
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def run(environment: Mapping[str, str]) -> int:
    summary_raw = environment.get("PROOFQA_SUMMARY_PATH", "").strip()
    if not summary_raw:
        raise ProofQAGateError("summary-path is required")
    report_raw = environment.get("PROOFQA_REPORT_PATH", "proofqa-gate-report.json").strip()
    if not report_raw:
        raise ProofQAGateError("report-path must not be empty")

    summary_path = Path(summary_raw)
    report_path = Path(report_raw)
    if report_path.is_symlink() or report_path.is_dir():
        raise ProofQAGateError(
            f"report-path must be a writable regular-file path: {report_path}"
        )

    summary = _load_json_object(summary_path, label="ProofQA summary")
    summary_resolved = summary_path.resolve(strict=True)
    report_resolved = report_path.resolve(strict=False)
    same_existing_file = report_path.exists() and os.path.samefile(
        summary_resolved, report_path
    )
    if report_resolved == summary_resolved or same_existing_file:
        raise ProofQAGateError("report-path must differ from summary-path")

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
    except (OSError, ProofQAGateError) as error:
        message = _escape_workflow_command(str(error))
        print(f"::error title=ProofQA configuration error::{message}")
        print(f"ProofQA gate error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
