"""Temporal and phase-aware relation verification for Ibex graph artifacts.

The runtime compares one declared relation with one observed relation and proves
whether the relation supported the exact transition at the exact phase and time.
It is deliberately non-authorizing: a match is evidence for a later policy gate,
not permission to execute or merge.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .canonical_json import CanonicalizationError, canonicalize_jcs, sha256_jcs

TEMPORAL_RELATION_CONTEXT = (
    "urn:ibex-agent-verification:temporal-phase-relation:v1"
)
TRANSITION_OBSERVATION_CONTEXT = (
    "urn:ibex-agent-verification:transition-observation:v1"
)
COMPARISON_CONTEXT = (
    "urn:ibex-agent-verification:expected-observed-transition-comparison:v1"
)

MATCH = "MATCH"
MISSING_OBSERVATION = "MISSING_OBSERVATION"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
PHASE_MISMATCH = "PHASE_MISMATCH"
TEMPORAL_MISMATCH = "TEMPORAL_MISMATCH"
STALE_EVIDENCE = "STALE_EVIDENCE"
OUTCOME_DEVIATION = "OUTCOME_DEVIATION"
NON_RECOMPUTABLE = "NON_RECOMPUTABLE"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOWED_RELATION_KEYS = {
    "@context",
    "source",
    "target",
    "relation_type",
    "transition_id",
    "expected_phase",
    "valid_from",
    "valid_until",
    "evidence_max_age_seconds",
    "expected_outcome",
    "evidence_refs",
}
_ALLOWED_OBSERVATION_KEYS = {
    "@context",
    "source",
    "target",
    "relation_type",
    "transition_id",
    "observed_phase",
    "observed_at",
    "observed_outcome",
    "evidence_refs",
}
_ALLOWED_ARTIFACT_KEYS = {"artifact_id", "artifact_type", "digest"}
_ALLOWED_EVIDENCE_KEYS = {"ref", "digest", "captured_at"}


def temporal_phase_relation_id(relation: Mapping[str, Any]) -> str:
    """Return the canonical identifier of a validated expected relation."""

    normalized = validate_temporal_phase_relation(relation)
    return sha256_jcs(normalized)


def transition_observation_id(observation: Mapping[str, Any]) -> str:
    """Return the canonical identifier of a validated observed relation."""

    normalized = validate_transition_observation(observation)
    return sha256_jcs(normalized)


def validate_temporal_phase_relation(
    relation: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and normalize a TemporalPhaseRelationV1 value."""

    value = _require_mapping(relation, "relation")
    _require_exact_keys(value, _ALLOWED_RELATION_KEYS, "relation")
    if value["@context"] != TEMPORAL_RELATION_CONTEXT:
        raise ValueError("relation @context is not TemporalPhaseRelationV1")

    valid_from = _parse_utc(value["valid_from"], "valid_from")
    valid_until = _parse_utc(value["valid_until"], "valid_until")
    if valid_until <= valid_from:
        raise ValueError("valid_until must be later than valid_from")

    max_age = value["evidence_max_age_seconds"]
    if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 0:
        raise ValueError("evidence_max_age_seconds must be a non-negative integer")

    normalized = {
        "@context": TEMPORAL_RELATION_CONTEXT,
        "source": _validate_artifact(value["source"], "source"),
        "target": _validate_artifact(value["target"], "target"),
        "relation_type": _require_text(value["relation_type"], "relation_type"),
        "transition_id": _require_text(value["transition_id"], "transition_id"),
        "expected_phase": _require_text(value["expected_phase"], "expected_phase"),
        "valid_from": _format_utc(valid_from),
        "valid_until": _format_utc(valid_until),
        "evidence_max_age_seconds": max_age,
        "expected_outcome": _validate_json_mapping(
            value["expected_outcome"], "expected_outcome"
        ),
        "evidence_refs": _validate_evidence_refs(value["evidence_refs"]),
    }
    canonicalize_jcs(normalized)
    return normalized


def validate_transition_observation(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and normalize a TransitionObservationV1 value."""

    value = _require_mapping(observation, "observation")
    _require_exact_keys(value, _ALLOWED_OBSERVATION_KEYS, "observation")
    if value["@context"] != TRANSITION_OBSERVATION_CONTEXT:
        raise ValueError("observation @context is not TransitionObservationV1")

    observed_at = _parse_utc(value["observed_at"], "observed_at")
    normalized = {
        "@context": TRANSITION_OBSERVATION_CONTEXT,
        "source": _validate_artifact(value["source"], "source"),
        "target": _validate_artifact(value["target"], "target"),
        "relation_type": _require_text(value["relation_type"], "relation_type"),
        "transition_id": _require_text(value["transition_id"], "transition_id"),
        "observed_phase": _require_text(value["observed_phase"], "observed_phase"),
        "observed_at": _format_utc(observed_at),
        "observed_outcome": _validate_json_mapping(
            value["observed_outcome"], "observed_outcome"
        ),
        "evidence_refs": _validate_evidence_refs(value["evidence_refs"]),
    }
    canonicalize_jcs(normalized)
    return normalized


def compare_expected_to_observed(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare expected and observed graph relations with deterministic precedence.

    The comparison is fail-closed. Any malformed or non-canonical value becomes
    NON_RECOMPUTABLE rather than leaking an exception through an authority path.
    """

    try:
        normalized_expected = validate_temporal_phase_relation(expected)
        expected_id = sha256_jcs(normalized_expected)
    except (CanonicalizationError, KeyError, TypeError, ValueError) as exc:
        return _comparison_record(
            status=NON_RECOMPUTABLE,
            expected_id=None,
            observed_id=None,
            mismatches=[{"field": "expected", "reason": str(exc)}],
        )

    if observed is None:
        return _comparison_record(
            status=MISSING_OBSERVATION,
            expected_id=expected_id,
            observed_id=None,
            mismatches=[{"field": "observed", "reason": "observation is missing"}],
        )

    try:
        normalized_observed = validate_transition_observation(observed)
        observed_id = sha256_jcs(normalized_observed)
    except (CanonicalizationError, KeyError, TypeError, ValueError) as exc:
        return _comparison_record(
            status=NON_RECOMPUTABLE,
            expected_id=expected_id,
            observed_id=None,
            mismatches=[{"field": "observed", "reason": str(exc)}],
        )

    identity_mismatches = _identity_mismatches(
        normalized_expected, normalized_observed
    )
    if identity_mismatches:
        return _comparison_record(
            status=IDENTITY_MISMATCH,
            expected_id=expected_id,
            observed_id=observed_id,
            mismatches=identity_mismatches,
        )

    if normalized_expected["expected_phase"] != normalized_observed["observed_phase"]:
        return _comparison_record(
            status=PHASE_MISMATCH,
            expected_id=expected_id,
            observed_id=observed_id,
            mismatches=[
                {
                    "field": "phase",
                    "expected": normalized_expected["expected_phase"],
                    "observed": normalized_observed["observed_phase"],
                }
            ],
        )

    observed_at = _parse_utc(normalized_observed["observed_at"], "observed_at")
    valid_from = _parse_utc(normalized_expected["valid_from"], "valid_from")
    valid_until = _parse_utc(normalized_expected["valid_until"], "valid_until")
    if not (valid_from <= observed_at < valid_until):
        return _comparison_record(
            status=TEMPORAL_MISMATCH,
            expected_id=expected_id,
            observed_id=observed_id,
            mismatches=[
                {
                    "field": "observed_at",
                    "expected": f"[{_format_utc(valid_from)}, {_format_utc(valid_until)})",
                    "observed": _format_utc(observed_at),
                }
            ],
        )

    stale = _stale_evidence(
        normalized_observed["evidence_refs"],
        observed_at,
        normalized_expected["evidence_max_age_seconds"],
    )
    if stale:
        return _comparison_record(
            status=STALE_EVIDENCE,
            expected_id=expected_id,
            observed_id=observed_id,
            mismatches=stale,
        )

    if canonicalize_jcs(normalized_expected["expected_outcome"]) != canonicalize_jcs(
        normalized_observed["observed_outcome"]
    ):
        return _comparison_record(
            status=OUTCOME_DEVIATION,
            expected_id=expected_id,
            observed_id=observed_id,
            mismatches=[
                {
                    "field": "outcome",
                    "expected": normalized_expected["expected_outcome"],
                    "observed": normalized_observed["observed_outcome"],
                }
            ],
        )

    return _comparison_record(
        status=MATCH,
        expected_id=expected_id,
        observed_id=observed_id,
        mismatches=[],
    )


def _comparison_record(
    *,
    status: str,
    expected_id: str | None,
    observed_id: str | None,
    mismatches: list[dict[str, Any]],
) -> dict[str, Any]:
    record = {
        "@context": COMPARISON_CONTEXT,
        "expected_relation_id": expected_id,
        "observed_relation_id": observed_id,
        "status": status,
        "transition_supported": status == MATCH,
        "transition_authorized": False,
        "blocking": status != MATCH,
        "mismatches": mismatches,
        "permitted_next_transition": (
            "EVALUATE_POLICY_GATE" if status == MATCH else "BLOCK_AND_RECONCILE"
        ),
    }
    record["comparison_id"] = sha256_jcs(record)
    return record


def _identity_mismatches(
    expected: Mapping[str, Any], observed: Mapping[str, Any]
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    pairs = (
        ("source", expected["source"], observed["source"]),
        ("target", expected["target"], observed["target"]),
        ("relation_type", expected["relation_type"], observed["relation_type"]),
        ("transition_id", expected["transition_id"], observed["transition_id"]),
    )
    for field, expected_value, observed_value in pairs:
        if canonicalize_jcs(expected_value) != canonicalize_jcs(observed_value):
            mismatches.append(
                {
                    "field": field,
                    "expected": expected_value,
                    "observed": observed_value,
                }
            )
    return mismatches


def _stale_evidence(
    refs: Sequence[Mapping[str, Any]],
    observed_at: datetime,
    max_age_seconds: int,
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for evidence in refs:
        captured_at = _parse_utc(evidence["captured_at"], "captured_at")
        age_seconds = int((observed_at - captured_at).total_seconds())
        if captured_at > observed_at:
            mismatches.append(
                {
                    "field": "evidence_refs",
                    "ref": evidence["ref"],
                    "reason": "evidence was captured after the observation",
                }
            )
        elif age_seconds > max_age_seconds:
            mismatches.append(
                {
                    "field": "evidence_refs",
                    "ref": evidence["ref"],
                    "reason": "evidence exceeded the declared freshness window",
                    "age_seconds": age_seconds,
                    "max_age_seconds": max_age_seconds,
                }
            )
    return mismatches


def _validate_artifact(value: Any, label: str) -> dict[str, str]:
    artifact = _require_mapping(value, label)
    _require_exact_keys(artifact, _ALLOWED_ARTIFACT_KEYS, label)
    digest = _require_text(artifact["digest"], f"{label}.digest")
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label}.digest must be a lowercase sha256 digest")
    return {
        "artifact_id": _require_text(artifact["artifact_id"], f"{label}.artifact_id"),
        "artifact_type": _require_text(
            artifact["artifact_type"], f"{label}.artifact_type"
        ),
        "digest": digest,
    }


def _validate_evidence_refs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise ValueError("evidence_refs must be a non-empty array")
    normalized: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        evidence = _require_mapping(item, f"evidence_refs[{index}]")
        _require_exact_keys(evidence, _ALLOWED_EVIDENCE_KEYS, f"evidence_refs[{index}]")
        digest = _require_text(evidence["digest"], f"evidence_refs[{index}].digest")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError(
                f"evidence_refs[{index}].digest must be a lowercase sha256 digest"
            )
        captured_at = _format_utc(
            _parse_utc(evidence["captured_at"], f"evidence_refs[{index}].captured_at")
        )
        normalized_item = {
            "ref": _require_text(evidence["ref"], f"evidence_refs[{index}].ref"),
            "digest": digest,
            "captured_at": captured_at,
        }
        identity = (normalized_item["ref"], normalized_item["digest"])
        if identity in identities:
            raise ValueError("evidence_refs must not contain duplicate ref/digest pairs")
        identities.add(identity)
        normalized.append(normalized_item)
    normalized.sort(key=lambda item: (item["ref"], item["digest"], item["captured_at"]))
    return normalized


def _validate_json_mapping(value: Any, label: str) -> dict[str, Any]:
    mapping = _require_mapping(value, label)
    normalized = dict(mapping)
    canonicalize_jcs(normalized)
    return normalized


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], allowed: set[str], label: str
) -> None:
    missing = sorted(allowed - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        raise ValueError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid RFC3339 UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{label} must be UTC")
    return parsed


def _format_utc(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond:
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")
