from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


class TrajectoryGateError(ValueError):
    """Raised when a trajectory gate input cannot be evaluated safely."""


MANDATORY_GATES = ("codex", "coderabbit", "deepseek", "ci")
DECISIONS = ("ALLOW", "BLOCK", "REPAIR", "SPLIT", "DEFER", "ROLLBACK")
SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "major": 2,
    "medium": 3,
    "minor": 4,
    "nit": 5,
    "info": 6,
}
REVIEWER_ORDER = {name: index for index, name in enumerate(MANDATORY_GATES)}


@dataclass(frozen=True)
class Finding:
    reviewer: str
    severity: str
    code: str
    message: str
    path: str = ""
    line: int = 0
    blocking: bool = True

    @classmethod
    def from_raw(
        cls, reviewer: str, raw: dict[str, Any], default_blocking: bool
    ) -> "Finding":
        if not isinstance(raw, dict):
            raise TrajectoryGateError(f"{reviewer} finding must be an object")
        return cls(
            reviewer=reviewer,
            severity=str(raw.get("severity") or "major").lower(),
            code=str(raw.get("code") or "UNSPECIFIED"),
            message=str(
                raw.get("message") or raw.get("reason") or "unspecified finding"
            ),
            path=str(raw.get("path") or ""),
            line=int(raw.get("line") or 0),
            blocking=bool(raw.get("blocking", default_blocking)),
        )

    def order_key(self) -> tuple[int, str, str, str, int]:
        return (
            SEVERITY_ORDER.get(self.severity, 99),
            self.reviewer,
            self.code,
            self.path,
            self.line,
        )

    def dedupe_key(self) -> tuple[str, str, str, int, bool]:
        return (self.code, self.message, self.path, self.line, self.blocking)

    def to_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "reviewer": self.reviewer,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
        }
        if self.path:
            item["path"] = self.path
        if self.line:
            item["line"] = self.line
        return item


def evaluate_trajectory_gate(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise TrajectoryGateError("record must be an object")
    repository = _required_str(record, "repository")
    pr_number = _required_int(record, "pr_number")
    head_sha = _required_str(record, "head_sha")
    gates = record.get("gates")
    if not isinstance(gates, dict):
        raise TrajectoryGateError("gates must be an object")

    normalized_gates: dict[str, dict[str, Any]] = {}
    all_findings: list[Finding] = []
    next_actions: list[str] = []

    for gate_name in MANDATORY_GATES:
        gate = gates.get(gate_name) or {
            "status": "MISSING",
            "reason": "mandatory gate is absent",
        }
        if not isinstance(gate, dict):
            raise TrajectoryGateError(f"gates.{gate_name} must be an object")
        normalized, gate_findings, actions = _normalize_gate(gate_name, gate, head_sha)
        normalized_gates[gate_name] = normalized
        all_findings.extend(gate_findings)
        next_actions.extend(actions)

    findings = _dedupe_findings(all_findings)
    blocking_findings = [item for item in findings if item.blocking]
    non_blocking_findings = [item for item in findings if not item.blocking]
    decision, reason = _select_decision(normalized_gates, blocking_findings)

    return {
        "schema_version": "trajectory-gate-report/v0.1",
        "repository": repository,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "observed_at": str(record.get("observed_at") or _utc_now()),
        "decision": decision,
        "best_next_transition": {"type": decision, "reason": reason},
        "candidate_transitions": _candidate_transitions(
            decision, reason, normalized_gates
        ),
        "gates": normalized_gates,
        "blocking_findings": [item.to_dict() for item in blocking_findings],
        "non_blocking_findings": [item.to_dict() for item in non_blocking_findings],
        "synthesis": {
            "agreements": _agreements(all_findings),
            "disagreements": [],
            "blind_spots": _blind_spots(normalized_gates),
            "trajectory_effect": _trajectory_effect(decision),
            "finding_order": "severity_desc, reviewer_asc, code_asc, path_asc, line_asc",
        },
        "required_next_actions": sorted({action for action in next_actions if action}),
        "gate_statuses": {
            name: gate["status"] for name, gate in normalized_gates.items()
        },
    }


def evaluate_trajectory_gate_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrajectoryGateError(f"invalid trajectory gate JSON: {exc}") from exc
    return evaluate_trajectory_gate(payload)


def _normalize_gate(
    name: str, gate: dict[str, Any], head_sha: str
) -> tuple[dict[str, Any], list[Finding], list[str]]:
    status = str(gate.get("status") or "MISSING").upper()
    applies_to_head = bool(gate.get("applies_to_head", gate.get("head_sha") == head_sha))
    reason = str(gate.get("reason") or "")
    actions: list[str] = []
    findings = _findings(name, gate)

    if not applies_to_head:
        status = "UNRESOLVED"
        reason = reason or "reviewer output does not apply to current head SHA"
        actions.append(f"refresh {name} output for current head SHA")

    if name == "deepseek":
        if gate.get("missing_api_key") is True:
            status = "BLOCKED"
            reason = "missing DEEPSEEK_API_KEY"
            actions.append("configure DEEPSEEK_API_KEY and rerun DeepSeek API review")
        elif gate.get("api_call_failed") is True:
            status = "BLOCKED"
            reason = reason or "DeepSeek API call failed"
            actions.append("fix DeepSeek API call and rerun review")
        elif gate.get("review_job_skipped") is True or status == "SKIPPED":
            status = "BLOCKED"
            reason = reason or "DeepSeek review job skipped"
            actions.append("rerun DeepSeek until a real API review completes")
        elif not bool(gate.get("api_review_completed", False)):
            status = "UNRESOLVED"
            reason = reason or "DeepSeek API review did not complete"
            actions.append("obtain completed DeepSeek API review")

    if name == "ci":
        if not bool(gate.get("exact_head", applies_to_head)):
            status = "UNRESOLVED"
            reason = reason or "CI result is not from exact head"
            actions.append("rerun CI on current head SHA")
        if status in {"FAILED", "FAILURE"} or gate.get("failed_checks"):
            status = "FAILED"
            reason = reason or "exact-head CI failed"
            actions.append("repair failing exact-head CI checks")

    if status in {"RATE_LIMITED", "MISSING", "PENDING", "SKIPPED"}:
        status = "BLOCKED" if status == "SKIPPED" else "UNRESOLVED"
        reason = reason or f"{name} gate did not produce approval"
        actions.append(f"rerun or restore {name} gate")

    if any(item.blocking for item in findings):
        actions.append(f"resolve blocking {name} findings")

    normalized_status = "PASS" if status in {"PASS", "SUCCESS", "APPROVED"} else status
    if normalized_status not in {"PASS", "FAILED", "BLOCKED"}:
        normalized_status = "UNRESOLVED"

    normalized: dict[str, Any] = {
        "status": normalized_status,
        "applies_to_head": applies_to_head,
        "head_sha": gate.get("head_sha"),
        "reason": reason or None,
        "blocking_findings": [item.to_dict() for item in findings if item.blocking],
        "non_blocking_findings": [
            item.to_dict() for item in findings if not item.blocking
        ],
    }
    if name == "deepseek":
        normalized["api_review_completed"] = bool(gate.get("api_review_completed", False))
    if name == "ci":
        normalized["exact_head"] = bool(gate.get("exact_head", applies_to_head))
        normalized["failed_checks"] = gate.get("failed_checks") or []
    return normalized, findings, actions


def _findings(name: str, gate: dict[str, Any]) -> list[Finding]:
    output = []
    for raw in gate.get("blocking_findings") or []:
        output.append(Finding.from_raw(name, raw, True))
    for raw in gate.get("non_blocking_findings") or []:
        output.append(Finding.from_raw(name, raw, False))
    return output


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    grouped: dict[tuple[str, str, str, int, bool], Finding] = {}
    for item in sorted(findings, key=lambda value: value.order_key()):
        grouped.setdefault(item.dedupe_key(), item)
    return sorted(grouped.values(), key=lambda value: value.order_key())


def _select_decision(
    gates: dict[str, dict[str, Any]], blocking_findings: list[Finding]
) -> tuple[str, str]:
    if any(gate["status"] == "FAILED" for gate in gates.values()):
        return "REPAIR", "At least one exact-head execution gate failed"
    if any(gate["status"] == "BLOCKED" for gate in gates.values()):
        return "BLOCK", "At least one fail-closed gate is blocked"
    if blocking_findings:
        return "REPAIR", "Blocking reviewer findings must be resolved"
    if any(gate["status"] == "UNRESOLVED" for gate in gates.values()):
        return "DEFER", "At least one mandatory gate is unresolved or stale"
    if all(gate["status"] == "PASS" for gate in gates.values()):
        return "ALLOW", "All mandatory gates passed on the current head"
    return "BLOCK", "No safe transition could be proven from the available evidence"


def _candidate_transitions(
    selected: str, reason: str, gates: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    unresolved = [name for name, gate in gates.items() if gate["status"] != "PASS"]
    rows = []
    for decision in DECISIONS:
        if decision == selected:
            rows.append({"type": decision, "status": "SELECTED", "reason": reason})
        elif decision == "ALLOW" and unresolved:
            rows.append(
                {
                    "type": decision,
                    "status": "REJECTED",
                    "reason": "mandatory gates are not all PASS",
                    "blocking_gates": unresolved,
                }
            )
        else:
            rows.append(
                {
                    "type": decision,
                    "status": "REJECTED",
                    "reason": f"{selected} is safer for the current evidence state",
                }
            )
    return rows


def _agreements(findings: list[Finding]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, int, bool], set[str]] = {}
    for item in findings:
        grouped.setdefault(item.dedupe_key(), set()).add(item.reviewer)
    rows = []
    for key, reviewers in grouped.items():
        if len(reviewers) > 1:
            code, message, path, line, blocking = key
            rows.append(
                {
                    "code": code,
                    "message": message,
                    "path": path or None,
                    "line": line or None,
                    "blocking": blocking,
                    "reviewers": _ordered_reviewers(reviewers),
                }
            )
    return sorted(rows, key=lambda item: (item["code"], item["path"] or "", item["line"] or 0))


def _ordered_reviewers(reviewers: set[str]) -> list[str]:
    return sorted(reviewers, key=lambda name: (REVIEWER_ORDER.get(name, 999), name))


def _blind_spots(gates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "gate": name,
            "reason": gate.get("reason") or "gate did not provide usable evidence",
        }
        for name, gate in sorted(gates.items())
        if gate["status"] != "PASS"
    ]


def _trajectory_effect(decision: str) -> str:
    return {
        "ALLOW": "Allows continuation only after all perspectives and exact-head evidence agree",
        "REPAIR": "Preserves trajectory by selecting repair before merge",
        "DEFER": "Prevents false certainty while current-head evidence is incomplete",
        "BLOCK": "Blocks an unsafe transition and protects evidence continuity",
        "SPLIT": "Reduces transition scope to recover reviewability",
        "ROLLBACK": "Rejects the current transition until a safer path is established",
    }[decision]


def _required_str(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise TrajectoryGateError(f"{key} must be a non-empty string")
    return value


def _required_int(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if not isinstance(value, int):
        raise TrajectoryGateError(f"{key} must be an integer")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
