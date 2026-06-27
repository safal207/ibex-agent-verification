#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts import proofqa_gate_v3 as json_support
    from scripts import proofqa_gate_v4 as gate
except ImportError:  # Direct execution from the scripts directory.
    import proofqa_gate_v3 as json_support
    import proofqa_gate_v4 as gate


class ProofQATransitionPreflightError(ValueError):
    """Raised when a transition report lacks safe, phase-appropriate evidence."""


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$")
_EVIDENCE_KEYS = {"intent_ref", "action_ref", "result_ref", "verification_ref"}
_REQUIRED_REFS = {
    "CALIBRATE": (),
    "EXPAND": ("intent_ref",),
    "COMMIT": ("intent_ref",),
    "EXECUTE": ("intent_ref", "action_ref"),
    "VERIFY": ("intent_ref", "action_ref", "result_ref"),
    "REFLECT": (
        "intent_ref",
        "action_ref",
        "result_ref",
        "verification_ref",
    ),
    "RECALIBRATE": (),
}


def _evidence_value(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 500
        or "\n" in value
        or "\r" in value
    ):
        raise ProofQATransitionPreflightError(
            f"transition.evidence.{field} must be null or a single-line non-empty string of at most 500 characters"
        )
    return value.strip()


def validate_transition_evidence(report: dict[str, Any]) -> dict[str, Any]:
    normalized = gate.validate_transition_report(report)
    transition_id = normalized["transition_id"]
    if not _ID_RE.fullmatch(transition_id):
        raise ProofQATransitionPreflightError(
            "transition.transition_id must use only letters, digits, dot, underscore, colon, slash, or hyphen"
        )

    evidence = report.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_KEYS:
        raise ProofQATransitionPreflightError(
            "transition.evidence must contain exactly intent_ref, action_ref, result_ref, and verification_ref"
        )
    normalized_evidence = {
        field: _evidence_value(evidence[field], field=field)
        for field in sorted(_EVIDENCE_KEYS)
    }

    if normalized["status"] == "IN_PROGRESS" and normalized["issues"]:
        raise ProofQATransitionPreflightError(
            "IN_PROGRESS transition must not contain issues; issues require RECALIBRATE"
        )

    required = _REQUIRED_REFS[normalized["phase"]]
    missing = [field for field in required if normalized_evidence[field] is None]
    if missing:
        raise ProofQATransitionPreflightError(
            f"transition phase {normalized['phase']} requires evidence references: {missing}"
        )

    return {
        **normalized,
        "evidence": normalized_evidence,
    }


def run(environment: Mapping[str, str]) -> int:
    policy = json_support._require_choice(
        environment.get("PROOFQA_TRANSITION_POLICY", "ignore"),
        name="transition-policy",
        choices={"ignore", "warn", "require-verified"},
    )
    if policy == "ignore":
        print("ProofQA transition preflight: disabled")
        return 0

    path_raw = environment.get("PROOFQA_TRANSITION_REPORT_PATH", "").strip()
    if not path_raw:
        raise ProofQATransitionPreflightError(
            f"transition-report-path is required when transition-policy={policy}"
        )
    path = Path(path_raw)
    report = json_support._load_json_object(
        path,
        label="ProofQA transition report",
    )
    normalized = validate_transition_evidence(report)
    print(
        "ProofQA transition preflight: "
        f"{normalized['transition_id']} {normalized['status']} {normalized['phase']}"
    )
    return 0


def main() -> int:
    try:
        return run(os.environ)
    except (
        OSError,
        json_support.ProofQAGateV3Error,
        gate.ProofQAGateV4Error,
        ProofQATransitionPreflightError,
    ) as error:
        message = json_support._escape_workflow_command(str(error))
        print(f"::error title=ProofQA transition preflight error::{message}")
        print(f"ProofQA transition preflight error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
