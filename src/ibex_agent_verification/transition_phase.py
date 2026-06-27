from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class TransitionPhaseError(ValueError):
    """Raised when a transition-phase record is malformed or contradictory."""


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$")
_PHASES = {
    "CALIBRATE",
    "EXPAND",
    "COMMIT",
    "EXECUTE",
    "VERIFY",
    "REFLECT",
    "RECALIBRATE",
}
_TOP_LEVEL_KEYS = {
    "schema_version",
    "transition_id",
    "time",
    "intention",
    "space",
    "evidence",
    "verification",
}
_TIME_KEYS = {
    "observed_before_ns",
    "intent_declared_ns",
    "commit_ns",
    "action_started_ns",
    "result_observed_ns",
    "evaluated_ns",
    "deadline_ns",
}
_INTENTION_KEYS = {
    "intent_id",
    "statement",
    "action",
    "expected_result",
    "stopping_condition",
}
_SPACE_KEYS = {"origin", "boundary", "destination"}
_EVIDENCE_KEYS = {"intent_ref", "action_ref", "result_ref", "verification_ref"}
_VERIFICATION_KEYS = {
    "result_matches_expectation",
    "destination_observed",
    "stopping_condition_met",
}
_TIME_ORDER = (
    "observed_before_ns",
    "intent_declared_ns",
    "commit_ns",
    "action_started_ns",
    "result_observed_ns",
    "evaluated_ns",
)


def _require_exact_keys(value: dict[str, Any], *, expected: set[str], path: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise TransitionPhaseError(
            f"{path} must contain exactly {sorted(expected)}; missing={missing} extra={extra}"
        )


def _object(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TransitionPhaseError(f"{path} must be an object")
    return value


def _optional_text(value: Any, *, path: str, maximum: int = 500) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise TransitionPhaseError(
            f"{path} must be null or a non-empty string of at most {maximum} characters"
        )
    return value.strip()


def _required_id(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise TransitionPhaseError(f"{path} is invalid: {value!r}")
    return value


def _optional_timestamp(value: Any, *, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TransitionPhaseError(f"{path} must be null or a non-negative integer")
    return value


def _optional_boolean(value: Any, *, path: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise TransitionPhaseError(f"{path} must be true, false, or null")


def load_transition_record(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TransitionPhaseError(
            f"transition record must be a regular non-symlink file: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TransitionPhaseError(
            f"{path}: invalid transition record JSON: {error.msg}"
        ) from error
    except OSError as error:
        raise TransitionPhaseError(f"cannot read transition record {path}: {error}") from error
    if not isinstance(payload, dict):
        raise TransitionPhaseError("transition record must be a JSON object")
    return payload


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    _require_exact_keys(record, expected=_TOP_LEVEL_KEYS, path="transition")
    if record.get("schema_version") != 1:
        raise TransitionPhaseError("transition.schema_version must equal 1")
    transition_id = _required_id(record.get("transition_id"), path="transition_id")

    raw_time = _object(record.get("time"), path="time")
    _require_exact_keys(raw_time, expected=_TIME_KEYS, path="time")
    time = {
        key: _optional_timestamp(raw_time.get(key), path=f"time.{key}")
        for key in _TIME_KEYS
    }
    if time["observed_before_ns"] is None:
        raise TransitionPhaseError("time.observed_before_ns is required")
    if time["evaluated_ns"] is None:
        raise TransitionPhaseError("time.evaluated_ns is required")

    raw_intention = _object(record.get("intention"), path="intention")
    _require_exact_keys(raw_intention, expected=_INTENTION_KEYS, path="intention")
    intention = {
        key: _optional_text(raw_intention.get(key), path=f"intention.{key}")
        for key in _INTENTION_KEYS
    }
    if intention["intent_id"] is not None:
        _required_id(intention["intent_id"], path="intention.intent_id")

    raw_space = _object(record.get("space"), path="space")
    _require_exact_keys(raw_space, expected=_SPACE_KEYS, path="space")
    space = {
        key: _optional_text(raw_space.get(key), path=f"space.{key}", maximum=240)
        for key in _SPACE_KEYS
    }
    if space["origin"] is None:
        raise TransitionPhaseError("space.origin is required")

    raw_evidence = _object(record.get("evidence"), path="evidence")
    _require_exact_keys(raw_evidence, expected=_EVIDENCE_KEYS, path="evidence")
    evidence = {
        key: _optional_text(raw_evidence.get(key), path=f"evidence.{key}", maximum=500)
        for key in _EVIDENCE_KEYS
    }

    raw_verification = _object(record.get("verification"), path="verification")
    _require_exact_keys(
        raw_verification,
        expected=_VERIFICATION_KEYS,
        path="verification",
    )
    verification = {
        key: _optional_boolean(raw_verification.get(key), path=f"verification.{key}")
        for key in _VERIFICATION_KEYS
    }

    return {
        "schema_version": 1,
        "transition_id": transition_id,
        "time": time,
        "intention": intention,
        "space": space,
        "evidence": evidence,
        "verification": verification,
    }


def _validate_chronology(time: dict[str, int | None]) -> None:
    previous_name: str | None = None
    previous_value: int | None = None
    for name in _TIME_ORDER:
        value = time[name]
        if value is None:
            continue
        if previous_value is not None and value < previous_value:
            raise TransitionPhaseError(
                f"time.{name} must not precede time.{previous_name}"
            )
        previous_name = name
        previous_value = value

    if time["commit_ns"] is not None and time["intent_declared_ns"] is None:
        raise TransitionPhaseError(
            "time.commit_ns requires time.intent_declared_ns; intention cannot be fabricated after commitment"
        )
    if time["action_started_ns"] is not None and time["commit_ns"] is None:
        raise TransitionPhaseError(
            "time.action_started_ns requires time.commit_ns; execution cannot precede commitment"
        )
    if time["result_observed_ns"] is not None and time["action_started_ns"] is None:
        raise TransitionPhaseError(
            "time.result_observed_ns requires time.action_started_ns"
        )
    if time["deadline_ns"] is not None:
        if time["deadline_ns"] < time["observed_before_ns"]:
            raise TransitionPhaseError(
                "time.deadline_ns must not precede time.observed_before_ns"
            )
    if time["evaluated_ns"] < time["observed_before_ns"]:
        raise TransitionPhaseError(
            "time.evaluated_ns must not precede time.observed_before_ns"
        )


def _all_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(mapping[key] is not None for key in keys)


def evaluate_transition(record: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_record(record)
    time = normalized["time"]
    intention = normalized["intention"]
    space = normalized["space"]
    evidence = normalized["evidence"]
    verification = normalized["verification"]
    _validate_chronology(time)

    intent_declared = _all_present(
        intention,
        ("intent_id", "statement"),
    ) and time["intent_declared_ns"] is not None and evidence["intent_ref"] is not None
    commitment_complete = intent_declared and _all_present(
        intention,
        ("action", "expected_result", "stopping_condition"),
    ) and _all_present(space, ("boundary", "destination")) and time["commit_ns"] is not None
    if space["destination"] is not None and space["destination"] == space["origin"]:
        raise TransitionPhaseError(
            "space.destination must differ from space.origin for a claimed transition"
        )

    execution_observed = (
        commitment_complete
        and time["action_started_ns"] is not None
        and evidence["action_ref"] is not None
    )
    result_observed = (
        execution_observed
        and time["result_observed_ns"] is not None
        and evidence["result_ref"] is not None
    )
    verification_complete = result_observed and _all_present(
        verification,
        (
            "result_matches_expectation",
            "destination_observed",
            "stopping_condition_met",
        ),
    ) and evidence["verification_ref"] is not None

    deadline_exceeded = (
        time["deadline_ns"] is not None
        and time["evaluated_ns"] > time["deadline_ns"]
        and not verification_complete
    )
    verification_failed = any(value is False for value in verification.values())

    if deadline_exceeded or verification_failed:
        phase = "RECALIBRATE"
    elif verification_complete:
        phase = "REFLECT"
    elif result_observed:
        phase = "VERIFY"
    elif execution_observed:
        phase = "EXECUTE"
    elif commitment_complete:
        phase = "COMMIT"
    elif intent_declared:
        phase = "EXPAND"
    else:
        phase = "CALIBRATE"

    temporal_status = "PASS"
    temporal_message = "Temporal order is valid for the observed transition events"
    if deadline_exceeded:
        temporal_status = "BLOCK"
        temporal_message = "Transition verification was not completed before the declared deadline"
    elif time["result_observed_ns"] is None:
        temporal_status = "WAIT"
        temporal_message = "The t+ result observation has not been recorded"

    intentional_status = "PASS"
    intentional_message = "Declared intention, committed action, expected result, and stopping condition are evidenced"
    if verification["result_matches_expectation"] is False or verification["stopping_condition_met"] is False:
        intentional_status = "BLOCK"
        intentional_message = "Observed result or stopping condition contradicts the committed intention"
    elif not commitment_complete:
        intentional_status = "WAIT"
        intentional_message = "A concrete pre-action commitment is incomplete"
    elif not verification_complete:
        intentional_status = "WAIT"
        intentional_message = "Committed intention has not yet been fully verified"

    spatial_status = "PASS"
    spatial_message = "Origin, crossed boundary, destination, and destination observation are evidenced"
    if verification["destination_observed"] is False:
        spatial_status = "BLOCK"
        spatial_message = "The declared destination was not observed"
    elif not _all_present(space, ("boundary", "destination")):
        spatial_status = "WAIT"
        spatial_message = "Boundary or destination is not yet declared"
    elif verification["destination_observed"] is not True:
        spatial_status = "WAIT"
        spatial_message = "The declared destination has not yet been verified"

    if phase == "REFLECT" and all(
        status == "PASS"
        for status in (temporal_status, intentional_status, spatial_status)
    ):
        status = "VERIFIED"
    elif phase == "RECALIBRATE":
        status = "RECALIBRATE"
    else:
        status = "IN_PROGRESS"

    next_phase = {
        "CALIBRATE": "EXPAND",
        "EXPAND": "COMMIT",
        "COMMIT": "EXECUTE",
        "EXECUTE": "VERIFY",
        "VERIFY": "REFLECT",
        "REFLECT": "CONTINUE",
        "RECALIBRATE": "CALIBRATE",
    }[phase]

    return {
        "schema_version": 1,
        "transition_id": normalized["transition_id"],
        "status": status,
        "phase": phase,
        "next_phase": next_phase,
        "axes": {
            "time": {
                "status": temporal_status,
                "t_minus_ns": time["observed_before_ns"],
                "t_zero_ns": time["commit_ns"],
                "t_plus_ns": time["result_observed_ns"],
                "deadline_ns": time["deadline_ns"],
                "message": temporal_message,
            },
            "intention": {
                "status": intentional_status,
                "intent_id": intention["intent_id"],
                "message": intentional_message,
            },
            "space": {
                "status": spatial_status,
                "origin": space["origin"],
                "boundary": space["boundary"],
                "destination": space["destination"],
                "message": spatial_message,
            },
        },
        "evidence": evidence,
        "claim_boundary": (
            "This report verifies the internal consistency and evidence completeness of one "
            "declared transition across time, intention, and space. It does not infer hidden "
            "intentions, fabricate presence in a destination, or prove that the external world "
            "changed beyond the supplied evidence references."
        ),
    }


def evaluate_transition_file(path: Path) -> dict[str, Any]:
    return evaluate_transition(load_transition_record(path))
