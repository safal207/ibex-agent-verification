"""Deterministic execution-safety classification for grant consumption.

This module does not dispatch tools or persist consumption state. It classifies
whether supplied deployment evidence is strong enough to claim replay-safe
execution across the authorization-to-side-effect boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ConsumptionMode(str, Enum):
    """Mechanism claimed to bind grant consumption to execution."""

    LOCAL_ATOMIC = "local_atomic"
    SHARED_ATOMIC = "shared_atomic"
    OUTBOX_ATOMIC = "outbox_atomic"
    TOOL_IDEMPOTENT = "tool_idempotent"
    ADVISORY_ONLY = "advisory_only"


class ExecutorScope(str, Enum):
    """Deployment scope sharing one consumption authority."""

    SINGLE_INSTANCE = "single_instance"
    MULTI_INSTANCE = "multi_instance"
    UNKNOWN = "unknown"


class ExecutionSafetyVerdict(str, Enum):
    """Fail-closed verdict for execution replay safety."""

    EXECUTION_SAFE = "EXECUTION_SAFE"
    REPLAY_PROTECTION_UNPROVEN = "REPLAY_PROTECTION_UNPROVEN"
    NOT_EXECUTION_SAFE = "NOT_EXECUTION_SAFE"
    USE_TOKEN_REQUIRED = "USE_TOKEN_REQUIRED"


class ExecutionGuarantee(str, Enum):
    """Maximum execution guarantee supported by the supplied evidence."""

    NONE = "NONE"
    ADVISORY = "ADVISORY"
    SINGLE_INSTANCE = "SINGLE_INSTANCE"
    ATOMIC = "ATOMIC"
    ATOMIC_ENQUEUE = "ATOMIC_ENQUEUE"
    IDEMPOTENT_ENDPOINT = "IDEMPOTENT_ENDPOINT"


_BINDING_FIELDS = (
    "execution_binding",
    "consumption_authority",
    "consumption_mode",
    "executor_scope",
    "dispatch_commitment_bound",
    "use_token",
    "use_token_bound",
    "endpoint_idempotency_enforced",
)
_EXECUTION_BINDINGS = frozenset({"internal", "external"})


@dataclass(frozen=True)
class ConsumptionBinding:
    """Closed evidence record for one grant-consumption boundary.

    ``dispatch_commitment_bound`` means the consumption state transition and
    the commitment that causes dispatch are one atomic unit. A separately
    issued HTTP/tool dispatch must therefore set it to ``False`` even when the
    ledger's own consume operation is atomic.

    ``use_token_bound`` means the stable endpoint idempotency token is derived
    from, or otherwise cryptographically/structurally bound to, the exact
    authorized grant occurrence. A caller-chosen fresh token per retry cannot
    provide replay protection across competing executors.
    """

    execution_binding: str
    consumption_authority: str
    consumption_mode: ConsumptionMode
    executor_scope: ExecutorScope
    dispatch_commitment_bound: bool
    use_token: str | None
    use_token_bound: bool
    endpoint_idempotency_enforced: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConsumptionBinding":
        """Parse the closed v1 record without guessing missing semantics."""

        if not isinstance(value, Mapping):
            raise TypeError("consumption binding must be a mapping")

        missing = [field for field in _BINDING_FIELDS if field not in value]
        if missing:
            raise ValueError(f"consumption binding missing required fields: {missing}")

        unknown = sorted(str(field) for field in value if field not in _BINDING_FIELDS)
        if unknown:
            raise ValueError(f"consumption binding contains unknown fields: {unknown}")

        execution_binding = value["execution_binding"]
        if not isinstance(execution_binding, str) or execution_binding not in _EXECUTION_BINDINGS:
            raise ValueError("execution_binding must be 'internal' or 'external'")

        consumption_authority = value["consumption_authority"]
        if not isinstance(consumption_authority, str) or not consumption_authority:
            raise ValueError("consumption_authority must be a non-empty string")

        try:
            consumption_mode = ConsumptionMode(value["consumption_mode"])
        except (TypeError, ValueError) as exc:
            raise ValueError("consumption_mode is not a supported closed value") from exc

        try:
            executor_scope = ExecutorScope(value["executor_scope"])
        except (TypeError, ValueError) as exc:
            raise ValueError("executor_scope is not a supported closed value") from exc

        dispatch_commitment_bound = value["dispatch_commitment_bound"]
        if not isinstance(dispatch_commitment_bound, bool):
            raise ValueError("dispatch_commitment_bound must be boolean")

        use_token = value["use_token"]
        if use_token is not None and (
            not isinstance(use_token, str) or not use_token
        ):
            raise ValueError("use_token must be null or a non-empty string")

        use_token_bound = value["use_token_bound"]
        if not isinstance(use_token_bound, bool):
            raise ValueError("use_token_bound must be boolean")

        endpoint_idempotency_enforced = value["endpoint_idempotency_enforced"]
        if not isinstance(endpoint_idempotency_enforced, bool):
            raise ValueError("endpoint_idempotency_enforced must be boolean")

        return cls(
            execution_binding=execution_binding,
            consumption_authority=consumption_authority,
            consumption_mode=consumption_mode,
            executor_scope=executor_scope,
            dispatch_commitment_bound=dispatch_commitment_bound,
            use_token=use_token,
            use_token_bound=use_token_bound,
            endpoint_idempotency_enforced=endpoint_idempotency_enforced,
        )


@dataclass(frozen=True)
class ExecutionSafetyResult:
    """Deterministic classification plus a stable machine-readable reason."""

    verdict: ExecutionSafetyVerdict
    guarantee: ExecutionGuarantee
    reason_code: str


def verify_execution_safety(binding: ConsumptionBinding) -> ExecutionSafetyResult:
    """Classify how far evidence reaches toward exclusive execution.

    The central invariant is ``Authority follows atomicity``: the component
    claiming consumption authority must be able to bind grant consumption to
    dispatch commitment in one atomic boundary, unless the final endpoint
    enforces the same occurrence-bound stable use token idempotently.
    """

    if not isinstance(binding, ConsumptionBinding):
        raise TypeError("binding must be a ConsumptionBinding")

    mode = binding.consumption_mode

    if mode is ConsumptionMode.ADVISORY_ONLY:
        return ExecutionSafetyResult(
            ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
            ExecutionGuarantee.ADVISORY,
            "ADVISORY_CHECK_THEN_ACT",
        )

    if mode is ConsumptionMode.TOOL_IDEMPOTENT:
        if binding.use_token is None:
            return ExecutionSafetyResult(
                ExecutionSafetyVerdict.USE_TOKEN_REQUIRED,
                ExecutionGuarantee.NONE,
                "USE_TOKEN_REQUIRED",
            )
        if not binding.use_token_bound:
            return ExecutionSafetyResult(
                ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
                ExecutionGuarantee.ADVISORY,
                "USE_TOKEN_BINDING_UNPROVEN",
            )
        if not binding.endpoint_idempotency_enforced:
            return ExecutionSafetyResult(
                ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
                ExecutionGuarantee.ADVISORY,
                "ENDPOINT_IDEMPOTENCY_UNPROVEN",
            )
        return ExecutionSafetyResult(
            ExecutionSafetyVerdict.EXECUTION_SAFE,
            ExecutionGuarantee.IDEMPOTENT_ENDPOINT,
            "ENDPOINT_IDEMPOTENCY_ENFORCED",
        )

    if not binding.dispatch_commitment_bound:
        return ExecutionSafetyResult(
            ExecutionSafetyVerdict.NOT_EXECUTION_SAFE,
            ExecutionGuarantee.NONE,
            "DISPATCH_OUTSIDE_ATOMIC_BOUNDARY",
        )

    if mode is ConsumptionMode.LOCAL_ATOMIC:
        if binding.executor_scope is not ExecutorScope.SINGLE_INSTANCE:
            return ExecutionSafetyResult(
                ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
                ExecutionGuarantee.SINGLE_INSTANCE,
                "LOCAL_STATE_NO_CROSS_INSTANCE_PROTECTION",
            )
        return ExecutionSafetyResult(
            ExecutionSafetyVerdict.EXECUTION_SAFE,
            ExecutionGuarantee.SINGLE_INSTANCE,
            "LOCAL_CONSUME_AND_DISPATCH_ATOMIC",
        )

    if mode is ConsumptionMode.OUTBOX_ATOMIC:
        return ExecutionSafetyResult(
            ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
            ExecutionGuarantee.ATOMIC_ENQUEUE,
            "OUTBOX_DELIVERY_REPLAY_PROTECTION_UNPROVEN",
        )

    if mode is ConsumptionMode.SHARED_ATOMIC:
        return ExecutionSafetyResult(
            ExecutionSafetyVerdict.EXECUTION_SAFE,
            ExecutionGuarantee.ATOMIC,
            "ATOMIC_CONSUME_AND_DISPATCH_COMMIT",
        )

    raise AssertionError(f"unhandled consumption mode: {mode}")
