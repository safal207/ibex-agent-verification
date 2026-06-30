from __future__ import annotations

from ibex_agent_verification.verifier_depth import validate_crosswalk


def _verdict(refs: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "decision_id": "gd_resource_001",
        "tool_call_id": "tc_resource_001",
        "label": "resource-test",
        "decision": "REPAIR",
        "reason_code": "TEST_FIXTURE",
        "policy_version": "policy-v1",
        "verifier_depth": "D2",
        "allowed_runtime_use": ["STRUCTURED_REPLAN"],
        "trust_domain": "tenant:demo",
        "claim_ceiling": "bounded-third-party-reproducible",
        "permitted_next_transition": "REPLAN_WITHIN_TRUST_DOMAIN",
        "evidence_refs": refs,
        "issued_at": "2026-06-30T12:00:00Z",
    }


def test_aggregate_evidence_bytes_fail_before_normalization() -> None:
    refs = [f"sha256:{index:064x}" for index in range(29)]
    result = validate_crosswalk(_verdict(refs), _verdict(refs))

    assert result["status"] == "INCOMPARABLE"
    assert result["reason"] == "INVALID_VERDICT_SHAPE"
    assert result["errors"]["a"] == ["EVIDENCE_REF_BYTES_EXCEEDED"]
    assert result["errors"]["b"] == ["EVIDENCE_REF_BYTES_EXCEEDED"]
