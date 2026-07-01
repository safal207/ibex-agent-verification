"""Canonical identifiers for verifiable agent action chains."""

from __future__ import annotations

import re
from typing import Any, Mapping

from ibex_agent_verification.canonical_json import CanonicalizationError, sha256_jcs
from ibex_agent_verification.schema_validation import (
    validate_action_envelope_v1,
    validate_guardrail_decision,
)

ACTION_ENVELOPE_V1_CONTEXT = "urn:ibex-agent-verification:action-envelope:v1"
ACTION_ENVELOPE_REQUIRED_FIELDS = (
    "tool_identity",
    "args_digest",
    "caller_identity",
    "resource_scope",
    "policy_version",
)
ACTION_ENVELOPE_V1_REQUIRED_FIELDS = (
    "@context",
    *ACTION_ENVELOPE_REQUIRED_FIELDS,
)
ACTION_ENVELOPE_OPTIONAL_FIELDS = ("authorization_deadline",)
DECISION_BINDING_REQUIRED_FIELDS = (
    "schema_version",
    "decision",
    "reason_code",
    "policy_version",
    "verifier_depth",
    "allowed_runtime_use",
    "trust_domain",
    "claim_ceiling",
    "permitted_next_transition",
    "evidence_refs",
    "issued_at",
)
DECISION_BOUND_AUTHORITY_FIELDS = (
    "schema_version",
    "decision",
    "policy_version",
    "verifier_depth",
    "allowed_runtime_use",
    "trust_domain",
    "claim_ceiling",
    "permitted_next_transition",
    "retry_policy",
    "suggested_replan_constraint",
    "required_remediation",
    "recompute_mode",
    "continuation_id",
    "action_id",
)
DECISION_BOUND_AUDIT_FIELDS = (
    "reason_code",
    "failure_class",
    "violated_boundary",
    "severity",
    "evidence_refs",
    "issued_at",
    "expires_at",
)
DECISION_EXPLICITLY_EXCLUDED_FIELDS = (
    "decision_id",
    "tool_call_id",
    "label",
    "estimated_cost_avoided",
    "cost_of_delay",
)
DECISION_CLASSIFIED_FIELDS = (
    *DECISION_BOUND_AUTHORITY_FIELDS,
    *DECISION_BOUND_AUDIT_FIELDS,
    *DECISION_EXPLICITLY_EXCLUDED_FIELDS,
)
_SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_action_id(envelope: Mapping[str, Any]) -> str:
    """Bind a continuation to one exact frozen authorization context.

    New adapters should provide the self-describing ActionEnvelopeV1 ``@context``.
    The unversioned field set remains accepted only for compatibility with the
    original published full-chain conformance vector.

    Unknown fields fail closed so an adapter cannot mutate an unbound part of
    the envelope between ``DEFER`` and resume.
    """

    if isinstance(envelope, Mapping) and "@context" in envelope:
        return canonical_action_envelope_v1_id(envelope)
    projection = _exact_projection(
        envelope,
        required=ACTION_ENVELOPE_REQUIRED_FIELDS,
        optional=ACTION_ENVELOPE_OPTIONAL_FIELDS,
        record_name="legacy action envelope",
    )
    return sha256_jcs(projection)


def canonical_action_envelope_v1_id(envelope: Mapping[str, Any]) -> str:
    """Validate and hash one self-describing ActionEnvelopeV1 record."""

    _validate_action_envelope_v1_record(envelope)
    projection = _exact_projection(
        envelope,
        required=ACTION_ENVELOPE_V1_REQUIRED_FIELDS,
        optional=ACTION_ENVELOPE_OPTIONAL_FIELDS,
        record_name="ActionEnvelopeV1",
    )
    return sha256_jcs(projection)


def canonical_decision_id(
    action_id: str,
    decision: Mapping[str, Any],
) -> str:
    """Bind validated evidence, audit facts, and authority to one frozen action."""

    _require_sha256_ref(action_id, "action_id")
    _validate_decision_record(decision)
    optional_fields = tuple(
        field
        for field in DECISION_CLASSIFIED_FIELDS
        if field not in DECISION_BINDING_REQUIRED_FIELDS
    )
    record = _exact_projection(
        decision,
        required=DECISION_BINDING_REQUIRED_FIELDS,
        optional=optional_fields,
        record_name="guardrail decision",
    )
    existing_action_id = record.get("action_id")
    if existing_action_id not in (None, action_id):
        raise ValueError("decision.action_id does not match the frozen action_id")

    projection = {
        field: record[field]
        for field in (*DECISION_BOUND_AUTHORITY_FIELDS, *DECISION_BOUND_AUDIT_FIELDS)
        if field in record and field != "action_id"
    }
    projection["action_id"] = action_id
    projection["allowed_runtime_use"] = _sorted_unique_strings(
        projection["allowed_runtime_use"],
        "allowed_runtime_use",
    )
    projection["evidence_refs"] = _sorted_unique_strings(
        projection["evidence_refs"],
        "evidence_refs",
    )
    return sha256_jcs(projection)


def canonical_chain_record_id(
    record_type: str,
    upstream_id: str,
    payload_ref: str,
) -> str:
    """Create one link in the action → decision → outcome → audit chain."""

    if not isinstance(record_type, str) or not record_type:
        raise ValueError("record_type must be a non-empty string")
    _require_sha256_ref(upstream_id, "upstream_id")
    _require_sha256_ref(payload_ref, "payload_ref")
    return sha256_jcs(
        {
            "payload_ref": payload_ref,
            "record_type": record_type,
            "upstream_id": upstream_id,
        }
    )


def continuation_matches(
    frozen_action_id: str,
    resumed_envelope: Mapping[str, Any],
) -> bool:
    """Fail closed unless resume reproduces the exact frozen action context."""

    if not isinstance(frozen_action_id, str) or _SHA256_REF.fullmatch(
        frozen_action_id
    ) is None:
        return False
    try:
        return canonical_action_id(resumed_envelope) == frozen_action_id
    except (CanonicalizationError, TypeError, ValueError):
        return False


def _validate_action_envelope_v1_record(envelope: Mapping[str, Any]) -> None:
    """Reject malformed or schema-invalid ActionEnvelopeV1 records before hashing."""

    if not isinstance(envelope, Mapping):
        raise TypeError("ActionEnvelopeV1 must be a mapping")
    errors = validate_action_envelope_v1(envelope)
    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"ActionEnvelopeV1 schema validation failed: {joined}")


def _validate_decision_record(decision: Mapping[str, Any]) -> None:
    """Reject malformed or schema-invalid decision records before hashing."""

    if not isinstance(decision, Mapping):
        raise TypeError("guardrail decision must be a mapping")
    errors = validate_guardrail_decision(decision)
    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"guardrail decision schema validation failed: {joined}")


def _exact_projection(
    source: Mapping[str, Any],
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    record_name: str,
    reject_unknown: bool = True,
) -> dict[str, Any]:
    """Project a locked field set and fail closed on missing or unknown fields."""

    if not isinstance(source, Mapping):
        raise TypeError(f"{record_name} must be a mapping")
    missing = [field for field in required if field not in source]
    if missing:
        raise ValueError(f"{record_name} missing required fields: {missing}")

    known = set(required) | set(optional)
    unknown = sorted(str(field) for field in source if field not in known)
    if reject_unknown and unknown:
        raise ValueError(f"{record_name} contains unknown fields: {unknown}")

    return {
        field: source[field]
        for field in (*required, *optional)
        if field in source
    }


def _sorted_unique_strings(value: Any, field_name: str) -> list[str]:
    """Normalize one semantic set using unsigned UTF-8 bytewise ordering."""

    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} must not contain duplicates")
    return sorted(value, key=lambda item: item.encode("utf-8"))


def _require_sha256_ref(value: Any, field_name: str) -> None:
    """Require the strict content-addressed identifier profile."""

    if not isinstance(value, str) or _SHA256_REF.fullmatch(value) is None:
        raise ValueError(f"{field_name} must match sha256:<64 lowercase hex>")
