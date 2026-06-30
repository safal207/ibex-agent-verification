from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from ibex_agent_verification.schema_validation import validate_guardrail_decision
from ibex_agent_verification.verifier_depth import (
    authorize_transition,
    canonical_action_id,
    continuation_matches,
    validate_crosswalk,
)


EVIDENCE_A = "sha256:" + "a" * 64
EVIDENCE_B = "sha256:" + "b" * 64


def _decision(depth: str, *uses: str) -> dict[str, object]:
    return {
        "verifier_depth": depth,
        "allowed_runtime_use": list(uses),
    }


def _envelope(**overrides: str) -> dict[str, str]:
    envelope = {
        "tool_identity": "send_email",
        "args_digest": "sha256:args-v1",
        "caller_identity": "agent:qa",
        "resource_scope": "workspace:demo",
        "policy_version": "policy-v1",
    }
    envelope.update(overrides)
    return envelope


def _verdict(label: str, **overrides: object) -> dict[str, object]:
    verdict: dict[str, object] = {
        "schema_version": 1,
        "decision_id": "gd_test_001",
        "tool_call_id": "tc_test_001",
        "label": label,
        "decision": "REPAIR",
        "reason_code": "TEST_FIXTURE",
        "policy_version": "policy-v1",
        "verifier_depth": "D2",
        "allowed_runtime_use": ["STRUCTURED_REPLAN"],
        "trust_domain": "tenant:demo",
        "claim_ceiling": "bounded-third-party-reproducible",
        "permitted_next_transition": "REPLAN_WITHIN_TRUST_DOMAIN",
        "evidence_refs": [EVIDENCE_A],
        "issued_at": "2026-06-30T12:00:00Z",
    }
    verdict.update(overrides)
    return verdict


def _assert_invalid(result: dict[str, object]) -> None:
    assert result["status"] == "INCOMPARABLE"
    assert result["reason"] == "INVALID_VERDICT_SHAPE"


def test_d0_allows_audit_when_explicitly_granted() -> None:
    result = authorize_transition(_decision("D0", "AUDIT_LOG"), "AUDIT_LOG")
    assert result["allowed"] is True


def test_d0_cannot_authorize_structured_replan() -> None:
    result = authorize_transition(
        _decision("D0", "STRUCTURED_REPLAN"),
        "STRUCTURED_REPLAN",
    )
    assert result == {
        "allowed": False,
        "reason": "INSUFFICIENT_VERIFIER_DEPTH",
        "required_depth": "D2",
        "actual_depth": "D0",
    }


def test_d1_allows_low_risk_repair_when_granted() -> None:
    result = authorize_transition(
        _decision("D1", "LOW_RISK_REPAIR"),
        "LOW_RISK_REPAIR",
    )
    assert result["allowed"] is True


def test_d1_cannot_publish_public_conformance() -> None:
    result = authorize_transition(
        _decision("D1", "PUBLIC_CONFORMANCE"),
        "PUBLIC_CONFORMANCE",
    )
    assert result["allowed"] is False
    assert result["reason"] == "INSUFFICIENT_VERIFIER_DEPTH"


def test_d2_allows_structured_replan_when_explicitly_granted() -> None:
    result = authorize_transition(
        _decision("D2", "STRUCTURED_REPLAN"),
        "STRUCTURED_REPLAN",
    )
    assert result["allowed"] is True


def test_d3_allows_public_conformance_when_explicitly_granted() -> None:
    result = authorize_transition(
        _decision("D3", "PUBLIC_CONFORMANCE"),
        "PUBLIC_CONFORMANCE",
    )
    assert result["allowed"] is True


def test_missing_depth_fails_closed() -> None:
    result = authorize_transition(
        {"allowed_runtime_use": ["AUDIT_LOG"]},
        "AUDIT_LOG",
    )
    assert result["allowed"] is False
    assert result["reason"] == "MISSING_VERIFIER_DEPTH"


def test_unknown_depth_fails_closed() -> None:
    result = authorize_transition(
        _decision("D9", "AUDIT_LOG"),
        "AUDIT_LOG",
    )
    assert result["allowed"] is False
    assert result["reason"] == "UNKNOWN_VERIFIER_DEPTH"


def test_depth_does_not_replace_explicit_runtime_grant() -> None:
    result = authorize_transition(_decision("D3"), "PUBLIC_CONFORMANCE")
    assert result["allowed"] is False
    assert result["reason"] == "RUNTIME_USE_NOT_GRANTED"


def test_unknown_transition_fails_closed() -> None:
    result = authorize_transition(_decision("D3", "DO_ANYTHING"), "DO_ANYTHING")
    assert result["allowed"] is False
    assert result["reason"] == "UNKNOWN_TRANSITION"


def test_action_id_is_stable_for_equivalent_mapping_order() -> None:
    left = _envelope()
    right = dict(reversed(list(left.items())))
    assert canonical_action_id(left) == canonical_action_id(right)


def test_changed_argument_digest_invalidates_continuation() -> None:
    frozen = canonical_action_id(_envelope())
    assert continuation_matches(frozen, _envelope(args_digest="sha256:args-v2")) is False


def test_changed_policy_invalidates_continuation() -> None:
    frozen = canonical_action_id(_envelope())
    assert continuation_matches(frozen, _envelope(policy_version="policy-v2")) is False


def test_unchanged_action_context_resumes() -> None:
    envelope = _envelope()
    assert continuation_matches(canonical_action_id(envelope), envelope) is True


def test_valid_fixture_executes_packaged_schema() -> None:
    assert validate_guardrail_decision(_verdict("D2")) == ()


def test_published_and_packaged_schemas_are_identical() -> None:
    public_schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas/guardrail-decision.schema.json").read_text(
            encoding="utf-8"
        )
    )
    packaged_schema = json.loads(
        files("ibex_agent_verification")
        .joinpath("schemas/guardrail-decision.schema.json")
        .read_text(encoding="utf-8")
    )
    assert public_schema == packaged_schema


def test_published_example_validates_against_runtime_schema() -> None:
    example = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/guardrail-decision.d2.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_guardrail_decision(example) == ()


def test_different_labels_with_same_transition_semantics_are_valid() -> None:
    result = validate_crosswalk(_verdict("bounded@anchor"), _verdict("D2"))
    assert result["status"] == "VALID"
    assert result["reason"] == "TRANSITION_SEMANTICS_PRESERVED"


def test_runtime_use_mismatch_is_collision() -> None:
    result = validate_crosswalk(
        _verdict("D3"),
        _verdict("D3", allowed_runtime_use=["AUDIT_LOG"]),
    )
    assert result["status"] == "COLLISION"
    assert "allowed_runtime_use" in result["mismatches"]


def test_decision_mismatch_is_collision() -> None:
    result = validate_crosswalk(
        _verdict("left", decision="ALLOW"),
        _verdict("right", decision="HARD_BLOCK", allowed_runtime_use=["AUDIT_LOG"]),
    )
    assert result["status"] == "COLLISION"
    assert "decision" in result["mismatches"]


def test_trust_domain_mismatch_is_collision() -> None:
    result = validate_crosswalk(
        _verdict("left", trust_domain="tenant:a"),
        _verdict("right", trust_domain="tenant:b"),
    )
    assert result["status"] == "COLLISION"
    assert "trust_domain" in result["mismatches"]


def test_crosswalk_with_different_evidence_is_incomparable() -> None:
    result = validate_crosswalk(
        _verdict("D2"),
        _verdict("bounded@anchor", evidence_refs=[EVIDENCE_B]),
    )
    assert result == {
        "status": "INCOMPARABLE",
        "reason": "EVIDENCE_MISMATCH",
    }


def test_crosswalk_evidence_refs_order_independent() -> None:
    a = _verdict("D2", evidence_refs=[EVIDENCE_A, EVIDENCE_B])
    b = _verdict("D3", evidence_refs=[EVIDENCE_B, EVIDENCE_A])
    assert validate_crosswalk(a, b)["status"] == "VALID"


def test_missing_evidence_fails_schema_closed() -> None:
    no_evidence = _verdict("D2")
    no_evidence.pop("evidence_refs")
    _assert_invalid(validate_crosswalk(no_evidence, _verdict("D2")))


def test_empty_evidence_fails_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(_verdict("D2", evidence_refs=[]), _verdict("D2"))
    )


def test_non_string_evidence_ref_fails_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", evidence_refs=[EVIDENCE_A, 7]),
            _verdict("D2"),
        )
    )


def test_duplicate_evidence_refs_fail_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", evidence_refs=[EVIDENCE_A, EVIDENCE_A]),
            _verdict("D2"),
        )
    )


def test_mutable_url_cannot_prove_same_evidence() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", evidence_refs=["https://example.org/latest.json"]),
            _verdict("D2", evidence_refs=["https://example.org/latest.json"]),
        )
    )


def test_overlong_evidence_ref_fails_schema_closed() -> None:
    bad_ref = "sha256:" + "a" * 494
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", evidence_refs=[bad_ref]),
            _verdict("D2", evidence_refs=[bad_ref]),
        )
    )


def test_oversized_evidence_array_fails_before_sorting() -> None:
    refs = [f"sha256:{index:064x}" for index in range(33)]
    result = validate_crosswalk(
        _verdict("D2", evidence_refs=refs),
        _verdict("D2", evidence_refs=refs),
    )
    _assert_invalid(result)
    assert result["errors"]["a"] == ["EVIDENCE_REF_COUNT_EXCEEDED"]


def test_missing_crosswalk_authority_fields_fail_closed() -> None:
    left = _verdict("D2")
    left.pop("claim_ceiling")
    left.pop("permitted_next_transition")
    _assert_invalid(validate_crosswalk(left, _verdict("D2")))


def test_wrong_runtime_use_type_fails_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", allowed_runtime_use="STRUCTURED_REPLAN"),
            _verdict("D2"),
        )
    )


def test_unknown_runtime_use_fails_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", allowed_runtime_use=["DO_ANYTHING"]),
            _verdict("D2"),
        )
    )


def test_duplicate_runtime_use_fails_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict(
                "D2",
                allowed_runtime_use=["STRUCTURED_REPLAN", "STRUCTURED_REPLAN"],
            ),
            _verdict("D2"),
        )
    )


def test_hard_block_cannot_carry_autonomous_runtime_grant() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict(
                "blocked",
                decision="HARD_BLOCK",
                allowed_runtime_use=["STRUCTURED_REPLAN"],
            ),
            _verdict(
                "blocked",
                decision="HARD_BLOCK",
                allowed_runtime_use=["STRUCTURED_REPLAN"],
            ),
        )
    )


def test_hard_block_with_audit_only_is_comparable() -> None:
    left = _verdict("blocked-a", decision="HARD_BLOCK", allowed_runtime_use=["AUDIT_LOG"])
    right = _verdict("blocked-b", decision="HARD_BLOCK", allowed_runtime_use=["AUDIT_LOG"])
    assert validate_crosswalk(left, right)["status"] == "VALID"


def test_additional_properties_fail_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", unexpected="value"),
            _verdict("D2"),
        )
    )


def test_invalid_date_time_fails_schema_closed() -> None:
    _assert_invalid(
        validate_crosswalk(
            _verdict("D2", issued_at="not-a-date"),
            _verdict("D2"),
        )
    )
