from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


class GateInputError(ValueError):
    """Raised when a silicon gate request or referenced evidence is invalid."""


@dataclass(frozen=True)
class GateReason:
    severity: str
    code: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class TimingMetrics:
    delay_anomalies: int
    unknown_delay_anomalies: int
    explained_delay_anomalies: int

    def to_dict(self) -> dict[str, int]:
        return {
            "delay_anomalies": self.delay_anomalies,
            "unknown_delay_anomalies": self.unknown_delay_anomalies,
            "explained_delay_anomalies": self.explained_delay_anomalies,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GateInputError(f"cannot read {label} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GateInputError(f"invalid JSON in {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateInputError(f"{label} must be a JSON object")
    return payload


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateInputError(f"{field} must be an object")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateInputError(f"{field} must be a non-empty string")
    return value.strip()


def _require_non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GateInputError(f"{field} must be a non-negative integer")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise GateInputError(f"{field} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_require_string(item, f"{field}[{index}]"))
    if len(result) != len(set(result)):
        raise GateInputError(f"{field} must not contain duplicates")
    return result


def _resolve_evidence(root: Path, raw_path: Any, field: str) -> Path:
    relative = Path(_require_string(raw_path, field))
    if relative.is_absolute():
        raise GateInputError(f"{field} must be relative to the gate request directory")
    resolved = (root / relative).resolve()
    root_resolved = root.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise GateInputError(f"{field} escapes the gate request directory")
    if not resolved.is_file():
        raise GateInputError(f"{field} does not exist: {relative.as_posix()}")
    return resolved


def _timing_metrics(report: dict[str, Any], label: str) -> TimingMetrics:
    findings = report.get("findings")
    if not isinstance(findings, list):
        raise GateInputError(f"{label}.findings must be an array")

    delay_anomalies = 0
    unknown = 0
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise GateInputError(f"{label}.findings[{index}] must be an object")
        if finding.get("status") != "DELAY_ANOMALY":
            continue
        delay_anomalies += 1
        cause = finding.get("primary_cause")
        if cause == "UNKNOWN" or cause is None:
            unknown += 1
        elif not isinstance(cause, str):
            raise GateInputError(
                f"{label}.findings[{index}].primary_cause must be a string or null"
            )

    declared = report.get("anomalies")
    if declared is not None:
        _require_non_negative_int(declared, f"{label}.anomalies")

    return TimingMetrics(
        delay_anomalies=delay_anomalies,
        unknown_delay_anomalies=unknown,
        explained_delay_anomalies=delay_anomalies - unknown,
    )


def _delayed_redirects(report: dict[str, Any], label: str) -> int:
    return _require_non_negative_int(
        report.get("delayed_redirects"), f"{label}.delayed_redirects"
    )


def _manifest_commit(manifest: dict[str, Any]) -> str:
    project = _require_object(manifest.get("project"), "manifest.project")
    return _require_string(project.get("commit"), "manifest.project.commit")


def evaluate_gate(request_path: str | Path) -> dict[str, Any]:
    request_file = Path(request_path).resolve()
    request = _load_json_object(request_file, "gate request")
    if request.get("schema_version") != 1:
        raise GateInputError("schema_version must be 1")

    change = _require_object(request.get("change"), "change")
    evidence = _require_object(request.get("evidence"), "evidence")
    policy = _require_object(request.get("policy"), "policy")

    request_id = _require_string(change.get("request_id"), "change.request_id")
    base_commit = _require_string(change.get("base_commit"), "change.base_commit")
    candidate_commit = _require_string(
        change.get("candidate_commit"), "change.candidate_commit"
    )
    changed_files = _string_list(change.get("changed_files"), "change.changed_files")
    risk_tags = _string_list(change.get("risk_tags", []), "change.risk_tags")

    actor = _require_object(change.get("actor"), "change.actor")
    actor_type = _require_string(actor.get("type"), "change.actor.type")
    actor_name = _require_string(actor.get("name"), "change.actor.name")
    actor_model = actor.get("model")
    require_ai_model = policy.get("require_ai_model", True)
    if not isinstance(require_ai_model, bool):
        raise GateInputError("policy.require_ai_model must be a boolean")
    if actor_type == "ai_agent" and require_ai_model:
        actor_model = _require_string(actor_model, "change.actor.model")
    elif actor_model is not None:
        actor_model = _require_string(actor_model, "change.actor.model")

    max_new_explained = _require_non_negative_int(
        policy.get("max_new_explained_timing_anomalies", 0),
        "policy.max_new_explained_timing_anomalies",
    )
    max_new_redirects = _require_non_negative_int(
        policy.get("max_new_delayed_redirects", 0),
        "policy.max_new_delayed_redirects",
    )
    manual_review_tags = _string_list(
        policy.get("manual_review_tags", []), "policy.manual_review_tags"
    )

    root = request_file.parent
    evidence_paths = {
        key: _resolve_evidence(root, evidence.get(key), f"evidence.{key}")
        for key in (
            "trace_comparison",
            "baseline_timing",
            "candidate_timing",
            "baseline_control_flow",
            "candidate_control_flow",
            "manifest",
        )
    }
    reports = {
        key: _load_json_object(path, key)
        for key, path in evidence_paths.items()
    }

    trace_status = _require_string(
        reports["trace_comparison"].get("status"), "trace_comparison.status"
    )
    baseline_timing = _timing_metrics(reports["baseline_timing"], "baseline_timing")
    candidate_timing = _timing_metrics(
        reports["candidate_timing"], "candidate_timing"
    )
    baseline_redirects = _delayed_redirects(
        reports["baseline_control_flow"], "baseline_control_flow"
    )
    candidate_redirects = _delayed_redirects(
        reports["candidate_control_flow"], "candidate_control_flow"
    )
    manifest_commit = _manifest_commit(reports["manifest"])

    new_unknown = max(
        0,
        candidate_timing.unknown_delay_anomalies
        - baseline_timing.unknown_delay_anomalies,
    )
    new_explained = max(
        0,
        candidate_timing.explained_delay_anomalies
        - baseline_timing.explained_delay_anomalies,
    )
    new_delayed_redirects = max(0, candidate_redirects - baseline_redirects)

    reasons: list[GateReason] = []
    if trace_status != "MATCH":
        reasons.append(
            GateReason(
                severity="BLOCK",
                code="ARCHITECTURAL_TRACE_MISMATCH",
                message="Candidate architectural trace does not match the oracle.",
                evidence={"trace_status": trace_status},
            )
        )

    if manifest_commit != candidate_commit:
        reasons.append(
            GateReason(
                severity="BLOCK",
                code="EVIDENCE_COMMIT_MISMATCH",
                message="Evidence manifest is not bound to the candidate commit.",
                evidence={
                    "candidate_commit": candidate_commit,
                    "manifest_commit": manifest_commit,
                },
            )
        )

    if new_unknown > 0:
        reasons.append(
            GateReason(
                severity="BLOCK",
                code="NEW_UNEXPLAINED_TIMING_ANOMALY",
                message="Candidate introduces delay anomalies without a supported cause.",
                evidence={"new_unknown_delay_anomalies": new_unknown},
            )
        )

    if new_explained > max_new_explained:
        reasons.append(
            GateReason(
                severity="BLOCK",
                code="EXPLAINED_TIMING_REGRESSION_LIMIT_EXCEEDED",
                message="Candidate exceeds the allowed explained timing regression budget.",
                evidence={
                    "new_explained_delay_anomalies": new_explained,
                    "allowed": max_new_explained,
                },
            )
        )
    elif new_explained > 0:
        reasons.append(
            GateReason(
                severity="ESCALATE",
                code="EXPLAINED_TIMING_REGRESSION_REQUIRES_REVIEW",
                message="Candidate adds explained timing anomalies within policy tolerance.",
                evidence={
                    "new_explained_delay_anomalies": new_explained,
                    "allowed": max_new_explained,
                },
            )
        )

    if new_delayed_redirects > max_new_redirects:
        reasons.append(
            GateReason(
                severity="BLOCK",
                code="BRANCH_REDIRECT_DELAY_LIMIT_EXCEEDED",
                message="Candidate exceeds the allowed delayed branch redirect budget.",
                evidence={
                    "new_delayed_redirects": new_delayed_redirects,
                    "allowed": max_new_redirects,
                },
            )
        )
    elif new_delayed_redirects > 0:
        reasons.append(
            GateReason(
                severity="ESCALATE",
                code="BRANCH_REDIRECT_DELAY_REQUIRES_REVIEW",
                message="Candidate adds delayed branch redirects within policy tolerance.",
                evidence={
                    "new_delayed_redirects": new_delayed_redirects,
                    "allowed": max_new_redirects,
                },
            )
        )

    matched_tags = sorted(set(risk_tags) & set(manual_review_tags))
    if matched_tags:
        reasons.append(
            GateReason(
                severity="ESCALATE",
                code="MANUAL_REVIEW_TAG",
                message="Policy requires human review for one or more declared risk tags.",
                evidence={"matched_tags": matched_tags},
            )
        )

    severities = {reason.severity for reason in reasons}
    if "BLOCK" in severities:
        decision = "BLOCK"
    elif "ESCALATE" in severities:
        decision = "ESCALATE"
    else:
        decision = "ALLOW"
        reasons.append(
            GateReason(
                severity="ALLOW",
                code="NO_EVIDENCE_REGRESSION",
                message="Required evidence is bound to the candidate and shows no regression.",
                evidence={},
            )
        )

    return {
        "schema_version": 1,
        "decision": decision,
        "request_id": request_id,
        "request_sha256": _sha256(request_file),
        "change": {
            "actor": {
                "type": actor_type,
                "name": actor_name,
                "model": actor_model,
            },
            "base_commit": base_commit,
            "candidate_commit": candidate_commit,
            "changed_files": changed_files,
            "risk_tags": risk_tags,
        },
        "policy": {
            "max_new_explained_timing_anomalies": max_new_explained,
            "max_new_delayed_redirects": max_new_redirects,
            "manual_review_tags": manual_review_tags,
            "require_ai_model": require_ai_model,
        },
        "checks": {
            "architectural_trace": trace_status,
            "evidence_commit_bound": manifest_commit == candidate_commit,
        },
        "metrics": {
            "baseline_timing": baseline_timing.to_dict(),
            "candidate_timing": candidate_timing.to_dict(),
            "new_unknown_delay_anomalies": new_unknown,
            "new_explained_delay_anomalies": new_explained,
            "baseline_delayed_redirects": baseline_redirects,
            "candidate_delayed_redirects": candidate_redirects,
            "new_delayed_redirects": new_delayed_redirects,
        },
        "reasons": [reason.to_dict() for reason in reasons],
        "evidence_files": {
            key: {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for key, path in sorted(evidence_paths.items())
        },
    }


def write_report(report: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate AI-generated silicon changes using reproducible evidence."
    )
    parser.add_argument("--request", required=True, help="gate request JSON path")
    parser.add_argument("--report", required=True, help="gate decision JSON path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_gate(args.request)
        write_report(report, args.report)
    except GateInputError as exc:
        payload = {"status": "INVALID_INPUT", "error": str(exc)}
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return {"ALLOW": 0, "BLOCK": 1, "ESCALATE": 3}[report["decision"]]


if __name__ == "__main__":
    raise SystemExit(main())
