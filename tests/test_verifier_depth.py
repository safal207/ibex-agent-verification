from __future__ import annotations

from ibex_agent_verification.verifier_depth import (
    authorize_transition,
    canonical_action_id,
    continuation_matches,
    validate_crosswalk,
)


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
        "label": label,
        "evidence_digest": "sha256:evidence",
        "allowed_runtime_use": ["STRUCTURED_REPLAN"],
        "claim_ceiling": "bounded-third-party-reproducible",
        "permitted_next_transition": "REPLAN_WITHIN_TRUST_DOMAIN",
    }
    verdict.update(overrides)
    return verdict


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


def test_different_labels_with_same_authority_tuple_are_valid() -> None:
    result = validate_crosswalk(_verdict("bounded@anchor"), _verdict("D2"))
    assert result["status"] == "VALID"


def test_same_label_with_different_authority_fails_closed() -> None:
    result = validate_crosswalk(
        _verdict("D3"),
        _verdict("D3", allowed_runtime_use=["AUDIT_LOG"]),
    )
    assert result["status"] == "COLLISION"
    assert "allowed_runtime_use" in result["mismatches"]


def test_crosswalk_with_different_evidence_is_incomparable() -> None:
    result = validate_crosswalk(
        _verdict("D2"),
        _verdict("bounded@anchor", evidence_digest="sha256:other"),
    )
    assert result == {
        "status": "INCOMPARABLE",
        "reason": "EVIDENCE_MISMATCH",
    }
