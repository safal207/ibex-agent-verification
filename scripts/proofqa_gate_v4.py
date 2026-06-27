#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts import proofqa_gate_v3 as base
except ImportError:  # Direct execution from the scripts directory.
    import proofqa_gate_v3 as base


class ProofQAGateV4Error(ValueError):
    """Raised when transition evidence or transition policy is invalid."""


@dataclass(frozen=True)
class GatePolicyV4:
    scorecard: base.GatePolicyV3
    transition_policy: str


_TRANSITION_STATUSES = {"VERIFIED", "IN_PROGRESS", "RECALIBRATE"}
_AXIS_STATUSES = {"PASS", "WAIT", "BLOCK"}
_PROGRESS_PHASES = {"CALIBRATE", "EXPAND", "COMMIT", "EXECUTE", "VERIFY"}
_NEXT_PHASE = {
    "CALIBRATE": "EXPAND",
    "EXPAND": "COMMIT",
    "COMMIT": "EXECUTE",
    "EXECUTE": "VERIFY",
    "VERIFY": "REFLECT",
    "REFLECT": "CONTINUE",
    "RECALIBRATE": "CALIBRATE",
}
_DECISION_ORDER = {"PASS": 0, "WARN": 1, "BLOCK": 2}


def policy_from_environment(environment: Mapping[str, str]) -> GatePolicyV4:
    return GatePolicyV4(
        scorecard=base.policy_from_environment(environment),
        transition_policy=base._require_choice(
            environment.get("PROOFQA_TRANSITION_POLICY", "ignore"),
            name="transition-policy",
            choices={"ignore", "warn", "require-verified"},
        ),
    )


def _non_empty_text(value: Any, *, label: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProofQAGateV4Error(
            f"{label} must be a non-empty string of at most {maximum} characters"
        )
    return value.strip()


def _validate_axis(axis: Any, *, name: str) -> str:
    if not isinstance(axis, dict):
        raise ProofQAGateV4Error(f"transition.axes.{name} must be an object")
    status = axis.get("status")
    if status not in _AXIS_STATUSES:
        raise ProofQAGateV4Error(
            f"transition.axes.{name}.status must be one of {sorted(_AXIS_STATUSES)}"
        )
    return status


def validate_transition_report(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != 1:
        raise ProofQAGateV4Error("transition.schema_version must equal 1")

    transition_id = _non_empty_text(
        report.get("transition_id"),
        label="transition.transition_id",
        maximum=160,
    )
    status = report.get("status")
    if status not in _TRANSITION_STATUSES:
        raise ProofQAGateV4Error(
            f"transition.status must be one of {sorted(_TRANSITION_STATUSES)}"
        )

    phase = report.get("phase")
    next_phase = report.get("next_phase")
    if phase not in _NEXT_PHASE:
        raise ProofQAGateV4Error(
            f"transition.phase must be one of {sorted(_NEXT_PHASE)}"
        )
    if next_phase != _NEXT_PHASE[phase]:
        raise ProofQAGateV4Error(
            f"transition.next_phase must equal {_NEXT_PHASE[phase]} for phase {phase}"
        )

    issues = report.get("issues")
    if not isinstance(issues, list) or any(
        not isinstance(item, str) or not item.strip() for item in issues
    ):
        raise ProofQAGateV4Error(
            "transition.issues must be an array of non-empty strings"
        )
    if len(set(issues)) != len(issues):
        raise ProofQAGateV4Error("transition.issues must not contain duplicates")

    axes = report.get("axes")
    if not isinstance(axes, dict) or set(axes) != {"time", "intention", "space"}:
        raise ProofQAGateV4Error(
            "transition.axes must contain exactly time, intention, and space"
        )
    axis_statuses = {
        name: _validate_axis(axes[name], name=name)
        for name in ("time", "intention", "space")
    }

    if status == "VERIFIED":
        if phase != "REFLECT" or next_phase != "CONTINUE":
            raise ProofQAGateV4Error(
                "VERIFIED transition must be in REFLECT with next_phase CONTINUE"
            )
        if issues:
            raise ProofQAGateV4Error("VERIFIED transition must have no issues")
        if set(axis_statuses.values()) != {"PASS"}:
            raise ProofQAGateV4Error(
                "VERIFIED transition requires PASS on time, intention, and space"
            )
    elif status == "IN_PROGRESS":
        if phase not in _PROGRESS_PHASES:
            raise ProofQAGateV4Error(
                "IN_PROGRESS transition must be in CALIBRATE, EXPAND, COMMIT, EXECUTE, or VERIFY"
            )
        if "BLOCK" in axis_statuses.values():
            raise ProofQAGateV4Error(
                "IN_PROGRESS transition cannot contain a BLOCK axis"
            )
    else:
        if phase != "RECALIBRATE" or next_phase != "CALIBRATE":
            raise ProofQAGateV4Error(
                "RECALIBRATE transition must use phase RECALIBRATE and next_phase CALIBRATE"
            )
        if not issues and "BLOCK" not in axis_statuses.values():
            raise ProofQAGateV4Error(
                "RECALIBRATE transition requires an issue or a BLOCK axis"
            )

    if not isinstance(report.get("evidence"), dict):
        raise ProofQAGateV4Error("transition.evidence must be an object")
    _non_empty_text(
        report.get("claim_boundary"),
        label="transition.claim_boundary",
        maximum=2000,
    )

    return {
        "transition_id": transition_id,
        "status": status,
        "phase": phase,
        "next_phase": next_phase,
        "issues": list(issues),
        "axis_statuses": axis_statuses,
    }


def _max_decision(first: str, second: str) -> str:
    return first if _DECISION_ORDER[first] >= _DECISION_ORDER[second] else second


def evaluate_transition_policy(
    *,
    policy: str,
    transition: dict[str, Any] | None,
) -> dict[str, Any]:
    if policy == "ignore":
        return {
            "finding": {
                "axis": "transition_phase",
                "label": "Transition phase",
                "direction": "exact",
                "actual": None,
                "unit": "state",
                "threshold": "VERIFIED",
                "warning_boundary": None,
                "enabled": False,
                "status": "PASS",
                "message": "Transition phase gate is disabled by policy",
            },
            "observation": None,
        }

    if transition is None:
        raise ProofQAGateV4Error(
            f"transition-report-path is required when transition-policy={policy}"
        )

    observed_status = transition["status"]
    if observed_status == "VERIFIED":
        finding_status = "PASS"
        message = (
            f"Transition {transition['transition_id']} is VERIFIED in REFLECT and may CONTINUE"
        )
    elif policy == "warn":
        finding_status = "WARN"
        message = (
            f"Transition {transition['transition_id']} is {observed_status} in phase "
            f"{transition['phase']}; transition-policy=warn"
        )
    else:
        finding_status = "BLOCK"
        message = (
            f"Transition {transition['transition_id']} is {observed_status} in phase "
            f"{transition['phase']}; require-verified permits only VERIFIED"
        )

    return {
        "finding": {
            "axis": "transition_phase",
            "label": "Transition phase",
            "direction": "exact",
            "actual": observed_status,
            "unit": "state",
            "threshold": "VERIFIED",
            "warning_boundary": None,
            "enabled": True,
            "status": finding_status,
            "message": message,
        },
        "observation": transition,
    }


def evaluate_gate(
    *,
    summary: dict[str, Any],
    policy: GatePolicyV4,
    transition: dict[str, Any] | None,
) -> dict[str, Any]:
    scorecard_evaluation = base.evaluate_gate(
        summary=summary,
        policy=policy.scorecard,
    )
    transition_evaluation = evaluate_transition_policy(
        policy=policy.transition_policy,
        transition=transition,
    )
    transition_finding = transition_evaluation["finding"]
    decision = _max_decision(
        scorecard_evaluation["decision"],
        transition_finding["status"],
    )
    should_fail = (
        policy.scorecard.fail_on == "warn" and decision in {"WARN", "BLOCK"}
    ) or (policy.scorecard.fail_on == "block" and decision == "BLOCK")
    return {
        "decision": decision,
        "should_fail": should_fail,
        "metrics": scorecard_evaluation["metrics"],
        "findings": [*scorecard_evaluation["findings"], transition_finding],
        "transition": transition_evaluation["observation"],
    }


def build_report(
    *,
    summary_path: Path,
    summary: dict[str, Any],
    transition_path: Path | None,
    policy: GatePolicyV4,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    transition = evaluation["transition"]
    source: dict[str, Any] = {
        "summary_path": str(summary_path),
        "summary_sha256": base._sha256(summary_path),
        "suite_id": summary["suite_id"],
        "provider": summary["provider"],
        "model": summary["model"],
        "scorecard_version": summary["scorecard_version"],
        "transition_report_path": None,
        "transition_report_sha256": None,
    }
    if transition_path is not None:
        source["transition_report_path"] = str(transition_path)
        source["transition_report_sha256"] = base._sha256(transition_path)

    scorecard_policy = policy.scorecard
    return {
        "schema_version": 3,
        "product": "ProofQA Release Gate",
        "decision": evaluation["decision"],
        "should_fail": evaluation["should_fail"],
        "source": source,
        "policy": {
            "name": scorecard_policy.policy_name,
            "min_end_to_end": scorecard_policy.min_end_to_end,
            "min_answer_correctness": scorecard_policy.min_answer_correctness,
            "min_completion_reliability": scorecard_policy.min_completion_reliability,
            "min_provider_reliability": scorecard_policy.min_provider_reliability,
            "warn_margin": scorecard_policy.warn_margin,
            "max_p95_duration_ms": scorecard_policy.max_p95_duration_ms,
            "time_warn_margin_ms": scorecard_policy.time_warn_margin_ms,
            "unknown_metric_policy": scorecard_policy.unknown_metric_policy,
            "transition_policy": policy.transition_policy,
            "fail_on": scorecard_policy.fail_on,
        },
        "metrics": evaluation["metrics"],
        "transition": transition,
        "findings": evaluation["findings"],
        "claim_boundary": (
            "The gate applies configured correctness, reliability, time, and transition "
            "policies to one ProofQA scorecard and, when enabled, one transition report. "
            "It validates the transition report contract but does not verify the external "
            "evidence referenced by that report or establish stable quality or latency "
            "without repeated, versioned evidence."
        ),
    }


def _display_finding(finding: dict[str, Any]) -> tuple[str, str]:
    if not finding["enabled"]:
        return "n/a", "disabled"
    if finding["unit"] == "percent":
        actual = base._display(finding["actual"], "percent")
        policy_text = f">= {finding['threshold']:.6f}%"
    elif finding["unit"] == "milliseconds":
        actual = base._display(finding["actual"], "milliseconds")
        policy_text = f"<= {finding['threshold']:.6f} ms"
    else:
        actual = str(finding["actual"])
        policy_text = f"= {finding['threshold']}"
    return actual, policy_text


def render_markdown(report: dict[str, Any]) -> str:
    icon = {"PASS": "✅", "WARN": "⚠️", "BLOCK": "🛑"}[report["decision"]]
    policy = report["policy"]
    source = report["source"]
    transition = report["transition"]
    lines = [
        f"## {icon} ProofQA Release Gate — {report['decision']}",
        "",
        f"- Policy: `{policy['name']}`",
        f"- Suite: `{source['suite_id']}`",
        f"- Provider/model: `{source['provider']}` / `{source['model']}`",
        f"- Scorecard: `v{source['scorecard_version']}`",
        f"- Summary SHA-256: `{source['summary_sha256']}`",
        f"- Transition policy: `{policy['transition_policy']}`",
        f"- Enforcement: `fail-on={policy['fail_on']}`",
    ]
    if transition is not None:
        lines.extend(
            [
                f"- Transition: `{transition['transition_id']}` — "
                f"`{transition['status']}` / `{transition['phase']}`",
                f"- Transition SHA-256: `{source['transition_report_sha256']}`",
            ]
        )
    lines.extend(
        [
            "",
            "| Axis | Actual | Policy | Result |",
            "|---|---:|---:|---|",
        ]
    )
    for finding in report["findings"]:
        actual, policy_text = _display_finding(finding)
        lines.append(
            f"| {finding['label']} | {actual} | {policy_text} | "
            f"`{finding['status']}` |"
        )
    lines.extend(["", "### Findings", ""])
    for finding in report["findings"]:
        lines.append(f"- **{finding['status']}** — {finding['message']}")
    lines.extend(["", f"Boundary: {report['claim_boundary']}", ""])
    return "\n".join(lines)


def _output_text(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _write_outputs(path: Path, report: dict[str, Any], report_path: Path) -> None:
    metrics = report["metrics"]
    transition = report["transition"]
    values = {
        "decision": report["decision"],
        "should-fail": str(report["should_fail"]).lower(),
        "report-path": str(report_path),
        "summary-sha256": report["source"]["summary_sha256"],
        "end-to-end-percent": base._output_number(metrics["end_to_end"]),
        "answer-correctness-percent": base._output_number(
            metrics["answer_correctness"]
        ),
        "completion-reliability-percent": base._output_number(
            metrics["completion_reliability"]
        ),
        "provider-reliability-percent": base._output_number(
            metrics["provider_reliability"]
        ),
        "p95-duration-ms": base._output_number(metrics["p95_duration_ms"]),
        "transition-status": _output_text(
            transition["status"] if transition is not None else None
        ),
        "transition-phase": _output_text(
            transition["phase"] if transition is not None else None
        ),
        "transition-sha256": _output_text(
            report["source"]["transition_report_sha256"]
        ),
    }
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def run(environment: Mapping[str, str]) -> int:
    summary_raw = environment.get("PROOFQA_SUMMARY_PATH", "").strip()
    if not summary_raw:
        raise ProofQAGateV4Error("summary-path is required")
    report_raw = environment.get(
        "PROOFQA_REPORT_PATH", "proofqa-gate-report.json"
    ).strip()
    if not report_raw:
        raise ProofQAGateV4Error("report-path must not be empty")

    summary_path = Path(summary_raw)
    report_path = Path(report_raw)
    if report_path.is_symlink() or report_path.is_dir():
        raise ProofQAGateV4Error(
            f"report-path must be a writable regular-file path: {report_path}"
        )

    policy = policy_from_environment(environment)
    transition_raw = environment.get("PROOFQA_TRANSITION_REPORT_PATH", "").strip()
    transition_path: Path | None = Path(transition_raw) if transition_raw else None
    if policy.transition_policy != "ignore" and transition_path is None:
        raise ProofQAGateV4Error(
            f"transition-report-path is required when transition-policy={policy.transition_policy}"
        )

    summary = base._load_json_object(summary_path, label="ProofQA summary")
    transition: dict[str, Any] | None = None
    if transition_path is not None and policy.transition_policy != "ignore":
        raw_transition = base._load_json_object(
            transition_path,
            label="ProofQA transition report",
        )
        transition = validate_transition_report(raw_transition)

    summary_resolved = summary_path.resolve(strict=True)
    report_resolved = report_path.resolve(strict=False)
    protected_sources = [summary_resolved]
    if transition_path is not None and policy.transition_policy != "ignore":
        protected_sources.append(transition_path.resolve(strict=True))
    for protected in protected_sources:
        same_existing_file = report_path.exists() and os.path.samefile(
            protected, report_path
        )
        if report_resolved == protected or same_existing_file:
            raise ProofQAGateV4Error(
                "report-path must differ from summary-path and transition-report-path"
            )

    evaluation = evaluate_gate(
        summary=summary,
        policy=policy,
        transition=transition,
    )
    report = build_report(
        summary_path=summary_path,
        summary=summary,
        transition_path=(
            transition_path if policy.transition_policy != "ignore" else None
        ),
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
            f"{base._escape_workflow_command(messages)}"
        )

    return 1 if report["should_fail"] else 0


def main() -> int:
    try:
        return run(os.environ)
    except (OSError, base.ProofQAGateV3Error, ProofQAGateV4Error) as error:
        message = base._escape_workflow_command(str(error))
        print(f"::error title=ProofQA configuration error::{message}")
        print(f"ProofQA gate error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
