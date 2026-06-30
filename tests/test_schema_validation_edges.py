from __future__ import annotations

from ibex_agent_verification.schema_validation import (
    load_guardrail_decision_schema,
    validate_guardrail_decision,
)
from ibex_agent_verification.verifier_depth import (
    evidence_resource_limits,
    validate_crosswalk,
)


EVIDENCE = "sha256:" + "a" * 64


def _verdict(**overrides: object) -> dict[str, object]:
    verdict: dict[str, object] = {
        "schema_version": 1,
        "decision_id": "gd_edge_001",
        "tool_call_id": "tc_edge_001",
        "label": "edge-test",
        "decision": "REPAIR",
        "reason_code": "TEST_FIXTURE",
        "policy_version": "policy-v1",
        "verifier_depth": "D2",
        "allowed_runtime_use": ["STRUCTURED_REPLAN"],
        "trust_domain": "tenant:demo",
        "claim_ceiling": "bounded-third-party-reproducible",
        "permitted_next_transition": "REPLAN_WITHIN_TRUST_DOMAIN",
        "evidence_refs": [EVIDENCE],
        "issued_at": "2026-06-30T12:00:00Z",
    }
    verdict.update(overrides)
    return verdict


def test_boolean_does_not_equal_integer_schema_version() -> None:
    errors = validate_guardrail_decision(_verdict(schema_version=True))
    assert errors
    assert any("schema_version" in error for error in errors)


def test_non_json_python_member_returns_invalid_shape_instead_of_raising() -> None:
    left = _verdict(evidence_refs=[{"not-json"}])
    result = validate_crosswalk(left, _verdict())

    assert result["status"] == "INCOMPARABLE"
    assert result["reason"] == "INVALID_VERDICT_SHAPE"
    assert "a" in result["invalid_sides"]


def test_runtime_resource_limits_are_derived_from_schema_metadata() -> None:
    schema = load_guardrail_decision_schema()["properties"]["evidence_refs"]
    limits = evidence_resource_limits()

    assert limits == {
        "max_refs": schema["maxItems"],
        "max_ref_chars": schema["items"]["maxLength"],
        "max_aggregate_bytes": schema["x-maxAggregateUtf8Bytes"],
    }
