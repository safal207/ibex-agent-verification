from __future__ import annotations

from enum import IntEnum
from typing import Any, Mapping

from ibex_agent_verification.action_chain import (
    canonical_action_id as _canonical_action_id,
    continuation_matches as _continuation_matches,
)
from ibex_agent_verification.schema_validation import (
    load_guardrail_decision_schema,
    validate_guardrail_decision,
)


class VerifierDepth(IntEnum):
    """Independent recomputability level for a guardrail verdict."""

    D0 = 0
    D1 = 1
    D2 = 2
    D3 = 3


REQUIRED_DEPTH: dict[str, VerifierDepth] = {
    "AUDIT_LOG": VerifierDepth.D0,
    "BOUNDED_RETRY": VerifierDepth.D1,
    "LOW_RISK_REPAIR": VerifierDepth.D1,
    "STRUCTURED_REPLAN": VerifierDepth.D2,
    "CONTROLLED_AUTONOMOUS_RETRY": VerifierDepth.D2,
    "PUBLIC_CONFORMANCE": VerifierDepth.D3,
    "EXTERNAL_CERTIFICATION": VerifierDepth.D3,
}


def _parse_depth(value: Any) -> VerifierDepth | None:
    """Parse a symbolic verifier depth, returning ``None`` for invalid input."""

    if not isinstance(value, str):
        return None
    try:
        return VerifierDepth[value]
    except KeyError:
        return None


def authorize_transition(
    decision: Mapping[str, Any],
    proposed_transition: str,
) -> dict[str, Any]:
    """Fail closed unless the verdict depth and explicit grant permit a transition."""

    required = REQUIRED_DEPTH.get(proposed_transition)
    if required is None:
        return {
            "allowed": False,
            "reason": "UNKNOWN_TRANSITION",
            "proposed_transition": proposed_transition,
        }

    if "verifier_depth" not in decision:
        return {
            "allowed": False,
            "reason": "MISSING_VERIFIER_DEPTH",
            "required_depth": required.name,
        }

    actual = _parse_depth(decision.get("verifier_depth"))
    if actual is None:
        return {
            "allowed": False,
            "reason": "UNKNOWN_VERIFIER_DEPTH",
            "required_depth": required.name,
        }

    if actual < required:
        return {
            "allowed": False,
            "reason": "INSUFFICIENT_VERIFIER_DEPTH",
            "required_depth": required.name,
            "actual_depth": actual.name,
        }

    granted = decision.get("allowed_runtime_use")
    if not isinstance(granted, list) or proposed_transition not in granted:
        return {
            "allowed": False,
            "reason": "RUNTIME_USE_NOT_GRANTED",
            "required_depth": required.name,
            "actual_depth": actual.name,
        }

    return {
        "allowed": True,
        "reason": "TRANSITION_AUTHORIZED",
        "required_depth": required.name,
        "actual_depth": actual.name,
    }


def canonical_action_id(envelope: Mapping[str, Any]) -> str:
    """Delegate to the canonical action-chain identifier implementation."""

    return _canonical_action_id(envelope)


def continuation_matches(
    frozen_action_id: str,
    resumed_envelope: Mapping[str, Any],
) -> bool:
    """Delegate fail-closed continuation checks to the action-chain implementation."""

    return _continuation_matches(frozen_action_id, resumed_envelope)


def evidence_resource_limits() -> dict[str, int]:
    """Return crosswalk resource limits from executable schema metadata."""

    schema = load_guardrail_decision_schema()
    evidence_schema = schema["properties"]["evidence_refs"]
    item_schema = evidence_schema["items"]
    limits = {
        "max_refs": evidence_schema["maxItems"],
        "max_ref_chars": item_schema["maxLength"],
        "max_aggregate_bytes": evidence_schema["x-maxAggregateUtf8Bytes"],
    }
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in limits.values()
    ):
        raise ValueError("invalid evidence resource-limit metadata")
    return limits


def _evidence_resource_error(verdict: Mapping[str, Any]) -> str | None:
    """Return the first pre-normalization evidence resource violation."""

    refs = verdict.get("evidence_refs")
    if not isinstance(refs, list):
        return None
    try:
        limits = evidence_resource_limits()
    except (KeyError, TypeError, ValueError):
        return "EVIDENCE_LIMIT_PROFILE_INVALID"

    if len(refs) > limits["max_refs"]:
        return "EVIDENCE_REF_COUNT_EXCEEDED"

    aggregate_bytes = 0
    for ref in refs:
        if not isinstance(ref, str):
            continue
        if len(ref) > limits["max_ref_chars"]:
            return "EVIDENCE_REF_LENGTH_EXCEEDED"
        aggregate_bytes += len(ref.encode("utf-8"))
        if aggregate_bytes > limits["max_aggregate_bytes"]:
            return "EVIDENCE_REF_BYTES_EXCEEDED"
    return None


def _crosswalk_profile_errors(verdict: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate crosswalk-only fields not required by the base decision schema."""

    errors: list[str] = []
    for field in ("claim_ceiling", "permitted_next_transition"):
        value = verdict.get(field)
        if not isinstance(value, str) or not value:
            errors.append(f"$.{field}: crosswalk requires a non-empty string")
    return tuple(errors)


def _evidence_key(verdict: Mapping[str, Any]) -> tuple[str, ...]:
    """Build an order-independent identity key for validated evidence refs."""

    refs = verdict["evidence_refs"]
    return tuple(sorted(refs))


def validate_crosswalk(
    verdict_a: Mapping[str, Any],
    verdict_b: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare complete transition semantics rather than vocabulary labels."""

    resource_errors = {
        side: error
        for side, error in (
            ("a", _evidence_resource_error(verdict_a)),
            ("b", _evidence_resource_error(verdict_b)),
        )
        if error is not None
    }
    if resource_errors:
        return {
            "status": "INCOMPARABLE",
            "reason": "INVALID_VERDICT_SHAPE",
            "invalid_sides": sorted(resource_errors),
            "errors": {
                side: [error] for side, error in resource_errors.items()
            },
        }

    schema_errors = {
        "a": validate_guardrail_decision(verdict_a)
        + _crosswalk_profile_errors(verdict_a),
        "b": validate_guardrail_decision(verdict_b)
        + _crosswalk_profile_errors(verdict_b),
    }
    invalid = {side: errors for side, errors in schema_errors.items() if errors}
    if invalid:
        return {
            "status": "INCOMPARABLE",
            "reason": "INVALID_VERDICT_SHAPE",
            "invalid_sides": sorted(invalid),
            "errors": {side: list(errors) for side, errors in invalid.items()},
        }

    evidence_a = _evidence_key(verdict_a)
    evidence_b = _evidence_key(verdict_b)
    if evidence_a != evidence_b:
        return {
            "status": "INCOMPARABLE",
            "reason": "EVIDENCE_MISMATCH",
        }

    fields = (
        "decision",
        "allowed_runtime_use",
        "claim_ceiling",
        "permitted_next_transition",
        "trust_domain",
    )

    def normalize(field: str, verdict: Mapping[str, Any]) -> Any:
        """Normalize order-insensitive fields before semantic comparison."""

        value = verdict[field]
        if field == "allowed_runtime_use":
            return tuple(sorted(value))
        return value

    mismatches = [
        field
        for field in fields
        if normalize(field, verdict_a) != normalize(field, verdict_b)
    ]
    if mismatches:
        return {
            "status": "COLLISION",
            "reason": "TRANSITION_SEMANTICS_MISMATCH",
            "mismatches": mismatches,
        }

    return {
        "status": "VALID",
        "reason": "TRANSITION_SEMANTICS_PRESERVED",
        "labels": [verdict_a.get("label"), verdict_b.get("label")],
    }
