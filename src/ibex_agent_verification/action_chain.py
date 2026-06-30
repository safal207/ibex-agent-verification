"""Canonical identifiers for verifiable agent action chains."""

from __future__ import annotations

import re
from typing import Any, Mapping

from ibex_agent_verification.canonical_json import CanonicalizationError, sha256_jcs

ACTION_ENVELOPE_REQUIRED_FIELDS = (
    "tool_identity",
    "args_digest",
    "caller_identity",
    "resource_scope",
    "policy_version",
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
DECISION_BINDING_OPTIONAL_FIELDS = ("expires_at",)
_SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_action_id(envelope: Mapping[str, Any]) -> str:
    """Bind a continuation to one exact frozen authorization context.

    Unknown fields fail closed so an adapter cannot mutate an unbound part of
    the envelope between ``DEFER`` and resume.
    """

    projection = _exact_projection(
        envelope,
        required=ACTION_ENVELOPE_REQUIRED_FIELDS,
        optional=ACTION_ENVELOPE_OPTIONAL_FIELDS,
        record_name="action envelope",
    )
    return sha256_jcs(projection)


def canonical_decision_id(
    action_id: str,
    decision: Mapping[str, Any],
) -> str:
    """Bind evidence and decision authority to one frozen action."""

    _require_sha256_ref(action_id, "action_id")
    projection = _exact_projection(
        decision,
        required=DECISION_BINDING_REQUIRED_FIELDS,
        optional=(
            *DECISION_BINDING_OPTIONAL_FIELDS,
            "action_id",
            "decision_id",
            "label",
            "tool_call_id",
        ),
        record_name="guardrail decision",
        reject_unknown=False,
    )
    existing_action_id = projection.get("action_id")
    if existing_action_id not in (None, action_id):
        raise ValueError("decision.action_id does not match the frozen action_id")

    projection.pop("decision_id", None)
    projection.pop("label", None)
    projection.pop("tool_call_id", None)
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
    """Normalize one semantic set without accepting malformed or duplicate items."""

    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} must not contain duplicates")
    return sorted(value)


def _require_sha256_ref(value: Any, field_name: str) -> None:
    """Require the strict content-addressed identifier profile."""

    if not isinstance(value, str) or _SHA256_REF.fullmatch(value) is None:
        raise ValueError(f"{field_name} must match sha256:<64 lowercase hex>")
