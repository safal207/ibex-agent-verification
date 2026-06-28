from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable


class TrajectoryGateError(ValueError):
    """Raised when a trajectory gate input cannot be evaluated safely."""


MANDATORY_GATES = ("codex", "coderabbit", "deepseek", "ci")
DECISIONS = ("ALLOW", "BLOCK", "REPAIR", "SPLIT", "DEFER", "ROLLBACK")
SEVERITY_ORDER = {"critical": 0, "high": 1, "major": 2, "medium": 3, "minor": 4, "nit": 5, "info": 6}


@dataclass(frozen=True)
class GateFinding:
    reviewer: str
    severity: str
    code: str
    message: str
    path: str | None = None
    line: int | None = None
    blocking: bool = True

    @classmethod
    def from_raw(cls, reviewer: str, raw: dict[str, Any]) -> "GateFinding":
        if not isinstance(raw, dict):
            raise TrajectoryGateError(f"{reviewer} finding must be an object")
        return cls(
            reviewer=reviewer,
            severity=str(raw.get("severity") or "major").lower(),
            code=str(raw.get("code") or "UNSPECIFIED"),
            message=str(raw.get("message") or raw.get("reason") or "unspecified finding"),
            path=raw.get("path"),
            line=raw.get("line"),
            blocking=bool(raw.get("blocking", True)),
        )

    def sort_key(self) -> tuple[int, str, str, str, int]:
        return (
            SEVERITY_ORDER.get(self.severity, 99),
            self.reviewer,
            self.code,
            self.path or "",
            self.line or 0,
        )

    def dedupe_key(self) -> tuple[str, str, str, int, bool]:
        return (self.code, self.message, self.path or "", self.line or 0, self.blocking)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "reviewer": self.reviewer,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
        }
        if self.path is not None:
            payload["path"] = self.path
        if self.line is not None:
            payload["line"] = self.line
        return payload


def evaluate_trajectory_gate(record: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a normalized multi-review PR state into a transition decision.

    This MVP is intentionally dependency-light and offline: GitHub/API collection happens
    before this function. The evaluator consumes normalized evidence and makes a
    deterministic fail-closed transition decision.
    """

    _require_object(record, "record")
    repository = _required_str(record, "repository")
    pr_number = _required_int(record, "pr_number")
    head_sha = _required_str(record, "head_sha")
    gates = record.get("gates")
    _require_object(gates, "gates")

    observed_at = str(record.get("observed_at") or _utc_now())
    normalized_gates: dict[str, Any] = {}
    all_findings: list[GateFinding] = []
    required_next_actions: list[str] = []

    for gate_name in MANDATORY_GATES:
        gate = gates.get(gate_name)
        if gate is None:
            gate = {"status": "MISSING", "reason": "mandatory gate is absent"}
        _require_object(gate, f"gates.{gate_name}")
        normalized, findings, next_actions = _evaluate_gate(gate_name, gate, head_sha)
        normalized_gates[gate_name] = normalized
        all_findings.extend(findings)
        required_next_actions.extend(next_actions)

    normalized_findings = _dedupe_findings(all_findings)
    blocking_findings = [finding for finding in normalized_findings if finding.blocking]
    non_blocking_findings = [finding for finding in normalized_findings if not finding.blocking]

    gate_statuses = {name: gate["status"] for name, gate in normalized_gates.items()}
    decision, reason = _select_transition(normalized_gates, blocking_findings)
    candidate_transitions = _candidate_transitions(decision, reason, normalized_gates)

    report = {
        "schema_version": "trajectory-gate-report/v0.1",
        "repository": repository,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "observed_at": observed_at,
        "decision": decision,
        "best_next_transition": {
            "type": decision,
            "reason": reason,
        },
        "candidate_transitions": candidate_transitions,
        "gates": normalized_gates,
        "blocking_findings": [finding.to_dict() for finding in blocking_findings],
        "non_blocking_findings": [finding.to_dict() for finding in non_blocking_findings],
        "synthesis": {
            "agreements": _agreements(normalized_findings),
            "disagreements": [],
            "blind_spots": _blind_spots(normalized_gates),
            "trajectory_effect": _trajectory_effect(decision),
            "finding_order": "severity_desc, reviewer_asc, code_asc, path_asc, line_asc",
        },
        "required_next_actions": _unique(required_next_actions),
        "gate_statuses": gate_statuses,
    }
    return report


def evaluate_trajectory_gate_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrajectoryGateError(f"invalid trajectory gate JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise TrajectoryGateError("trajectory gate record must be a JSON object")
    return evaluate_trajectory_gate(record)


def _evaluate_gate(
    gate_name: str, gate: dict[str, Any], head_sha: str
) -> tuple[dict[str, Any], list[GateFinding], list[str]]:
    status = str(gate.get("status") or "MISSING").upper()
    applies_to_head = bool(gate.get("applies_to_head", gate.get("head_sha") == head_sha))
    reason = str(gate.get("reason") or "")
    findings = _load_findings(gate_name, gate)
    next_actions: list[str] = []

    if not applies_to_head:
        status = "UNRESOLVED"
        reason = reason or "reviewer output does not apply to current head SHA"
        next_actions.append(f"refresh {gate_name} output for current head SHA")

    if gate_name == "deepseek":
        api_review_completed = bool(gate.get("api_review_completed", False))
        if gate.get("missing_api_key") is True:
            status = "BLOCKED"
            reason = "missing DEEPSEEK_API_KEY"
            next_actions.append("configure DEEPSEEK_API_KEY and rerun DeepSeek API review")
        elif gate.get("api_call_failed") is True:
            status = "BLOCKED"
            reason = reason or "DeepSeek API call failed"
            next_actions.append("fix DeepSeek API call and rerun review")
        elif gate.get("review_job_skipped") is True or status == "SKIPPED":
            status = "BLOCKED"
            reason = reason or "DeepSeek review job skipped"
            next_actions.append("rerun DeepSeek until a real API review completes")
        elif not api_review_completed:
            status = "UNRESOLVED"
            reason = reason or "DeepSeek API review did not complete"
            next_actions.append("obtain completed DeepSeek API review")

    if gate_name == "ci":
        exact_head = bool(gate.get("exact_head", applies_to_head))
        if not exact_head:
            status = "UNRESOLVED"
            reason = reason or "CI result is not from exact head"
            next_actions.append("rerun CI on current head SHA")
        failed_checks = gate.get("failed_checks") or []
        if status in {"FAILED", "FAILURE"} or failed_checks:
            status = "FAILED"
            reason = reason or "exact-head CI failed"
            next_actions.append("repair failing exact-head CI checks")

    if status in {"RATE_LIMITED", "MISSING", "PENDING", "SKIPPED"}:
        status = "UNRESOLVED" if status != "SKIPPED" else "BLOCKED"
        reason = reason or f"{gate_name} gate did not produce approval"
        next_actions.append(f"rerun or restore {gate_name} gate")

    if any(finding.blocking for finding in findings):
        if status in {"PASS", "SUCCESS", "APPROVED"}:
            status = "UNRESOLVED"
        next_actions.append(f"resolve blocking {gate_name} findings")

    if status in {"PASS", "SUCCESS", "APPROVED"}:
        normalized_status = "PASS"
    elif status in {"FAILED", "FAILURE"}:
        normalized_status = "FAILED"
    elif status == "BLOCKED":
        normalized_status = "BLOCKED"
    else:
        normalized_status = "UNRESOLVED"

    normalized = {
        "status": normalized_status,
        "applies_to_head": applies_to_head,
        "head_sha": gate.get("head_sha"),
        "reason": reason or None,
        "blocking_findings": [finding.to_dict() for finding in findings if finding.blocking],
        "non_blocking_findings": [finding.to_dict() for finding in findings if not finding.blocking],
    }
    if gate_name == "deepseek":
        normalized["api_review_completed"] = bool(gate.get("api_review_completed", False))
    if gate_name == "ci":
        normalized["exact_head"] = bool(gate.get("exact_head", applies_to_head))
        normalized["failed_checks"] = gate.get("failed_checks") or []

    return normalized, findings, next_actions


def _load_findings(reviewer: str, gate: dict[str, Any]) -> list[GateFinding]:
    raw_findings: list[Any] = []
    raw_findings.extend(gate.get("blocking_findings") or [])
    raw_findings.extend(gate.get("non_blocking_findings") or [])
    findings: list[GateFinding] = []
    blocking_count = len(gate.get("blocking_findings") or [])
    for index, raw in enumerate(raw_findings):
        finding = GateFinding.from_raw(reviewer, raw)
        if index >= blocking_count and "blocking" not in raw:
            finding = GateFinding(
                reviewer=finding.reviewer,
                severity=finding.severity,
                code=finding.code,
                message=finding.message,
                path=finding.path,
                line=finding.line,
                blocking=False,
            )
        findings.append(finding)
    return findings


def _dedupe_findings(findings: Iterable[GateFinding]) -> list[GateFinding]:
    by_key: dict[tuple[str, str, str, int, bool], GateFinding] = {}
    for finding in sorted(findings, key=lambda item: item.sort_key()):
        by_key.setdefault(finding.dedupe_key(), finding)
    return sorted(by_key.values(), key=lambda item: item.sort_key())


def _select_transition(
    gates: dict[str, dict[str, Any]], blocking_findings: list[GateFinding]
) -> tuple[str, str]:
    if any(gate["status"] == "FAILED" for gate in gates.values()):
        return "REPAIR", "At least one exact-head execution gate failed"
    if any(gate["status"] == "BLOCKED" for gate in gates.values()):
        return "BLOCK", "At least one fail-closed gate is blocked"
    if any(gate["status"] == "UNRESOLVED" for gate in gates.values()):
        return "DEFER", "At least one mandatory gate is unresolved or stale"
    if blocking_findings:
        return "REPAIR", "Blocking reviewer findings must be resolved"
    if all(gate["status"] == "PASS" for gate in gates.values()):
        return "ALLOW", "All mandatory gates passed on the current head"
    return "BLOCK", "No safe transition could be proven from the available evidence"


def _candidate_transitions(
    selected: str, reason: str, gates: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    unresolved = [name for name, gate in gates.items() if gate["status"] != "PASS"]
    candidates = []
    for decision in DECISIONS:
        if decision == selected:
            candidates.append({"type": decision, "status": "SELECTED", "reason": reason})
        elif decision == "ALLOW" and unresolved:
            candidates.append(
                {
                    "type": decision,
                    "status": "REJECTED",
                    "reason": "mandatory gates are not all PASS",
                    "blocking_gates": unresolved,
                }
            )
        else:
            candidates.append(
                {
                    "type": decision,
                    "status": "REJECTED",
                    "reason": f"{selected} is safer for the current evidence state",
                }
            )
    return candidates


def _agreements(findings: list[GateFinding]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, int, bool], set[str]] = {}
    for finding in findings:
        grouped.setdefault(finding.dedupe_key(), set()).add(finding.reviewer)
    agreements = []
    for key, reviewers in grouped.items():
        if len(reviewers) > 1:
            code, message, path, line, blocking = key
            agreements.append(
                {
                    "code": code,
                    "message": message,
                    "path": path or None,
                    "line": line or None,
                    "blocking": blocking,
                    "reviewers": sorted(reviewers),
                }
            )
    return sorted(agreements, key=lambda item: (item["code"], item["path"] or "", item["line"] or 0))


def _blind_spots(gates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"gate": name, "reason": gate.get("reason") or "gate did not provide usable evidence"}
        for name, gate in sorted(gates.items())
        if gate["status"] != "PASS"
    ]


def _trajectory_effect(decision: str) -> str:
    if decision == "ALLOW":
        return "Allows continuation only after all perspectives and exact-head evidence agree"
    if decision == "REPAIR":
        return "Preserves trajectory by selecting repair before merge"
    if decision == "DEFER":
        return "Prevents false certainty while current-head evidence is incomplete"
    if decision == "BLOCK":
        return "Blocks an unsafe transition and protects evidence continuity"
    if decision == "SPLIT":
        return "Reduces transition scope to recover reviewability"
    return "Rejects the current transition until a safer path is established"


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


def _require_object(value: Any, name: str) -> None:
    if not isinstance(value, dict):
        raise TrajectoryGateError(f"{name} must be an object")


def _unique(items: Iterable[str]) -> list[str]:
    return sorted({item for item in items if item})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
