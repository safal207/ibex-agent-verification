"""CrewAI-compatible ActionEnvelopeV1 authorization core."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from ibex_agent_verification.action_chain import (
    ACTION_ENVELOPE_V1_CONTEXT,
    canonical_action_envelope_v1_id,
)
from ibex_agent_verification.canonical_json import sha256_jcs


@runtime_checkable
class CrewAIToolCallContext(Protocol):
    """Structural subset of CrewAI's ToolCallHookContext."""

    tool_name: str
    tool_input: dict[str, Any]
    tool: Any
    agent: Any | None
    task: Any | None
    crew: Any | None


@dataclass(frozen=True)
class CrewAIAdapterConfig:
    """Stable values that cannot be derived safely from one tool call."""

    resource_scope: str
    policy_version: str
    fail_closed: bool = True
    authorization_deadline: str | None = None


@dataclass(frozen=True)
class CrewAIGuardrailRequest:
    """Frozen request passed to a provider for one CrewAI tool call."""

    action_id: str
    action_envelope: Mapping[str, Any]
    tool_name: str
    sanitized_tool_name: str
    tool_input: Mapping[str, Any]
    agent_id: str | None = None
    agent_role: str | None = None
    task_description: str | None = None


@dataclass(frozen=True)
class CrewAIGuardrailDecision:
    """Minimal CrewAI-facing allow or deny decision."""

    allow: bool
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class CrewAIGuardrailProvider(Protocol):
    """Provider contract consumed by the CrewAI hook adapter."""

    name: str

    def evaluate(self, request: CrewAIGuardrailRequest) -> CrewAIGuardrailDecision:
        """Return a synchronous authorization decision for one frozen action."""
        ...


def build_crewai_action_envelope(
    context: CrewAIToolCallContext,
    config: CrewAIAdapterConfig,
) -> dict[str, Any]:
    """Build and validate ActionEnvelopeV1 from a CrewAI hook context."""

    sanitized_name = _required_text(context.tool_name, "context.tool_name")
    tool_name = _optional_text_attr(context.tool, "name") or sanitized_name
    tool_input = _snapshot_tool_input(context.tool_input)
    agent_id = _optional_identity_attr(context.agent, "id")
    agent_role = _optional_text_attr(context.agent, "role")

    if agent_id is not None:
        caller_identity = _identity_ref("crewai-agent-id", agent_id)
    elif agent_role is not None:
        caller_identity = _identity_ref("crewai-agent-role", agent_role)
    else:
        caller_identity = "crewai-agent:anonymous"

    envelope: dict[str, Any] = {
        "@context": ACTION_ENVELOPE_V1_CONTEXT,
        "tool_identity": _identity_ref("crewai-tool", tool_name),
        "args_digest": sha256_jcs(tool_input),
        "caller_identity": caller_identity,
        "resource_scope": config.resource_scope,
        "policy_version": config.policy_version,
    }
    if config.authorization_deadline is not None:
        envelope["authorization_deadline"] = config.authorization_deadline

    canonical_action_envelope_v1_id(envelope)
    return envelope


def evaluate_crewai_tool_call(
    context: CrewAIToolCallContext,
    provider: CrewAIGuardrailProvider,
    config: CrewAIAdapterConfig,
) -> bool | None:
    """Return CrewAI hook semantics: False blocks, None allows."""

    try:
        envelope = build_crewai_action_envelope(context, config)
        action_id = canonical_action_envelope_v1_id(envelope)
        tool_name = _optional_text_attr(context.tool, "name") or context.tool_name
        request = CrewAIGuardrailRequest(
            action_id=action_id,
            action_envelope=deepcopy(envelope),
            tool_name=tool_name,
            sanitized_tool_name=context.tool_name,
            tool_input=_snapshot_tool_input(context.tool_input),
            agent_id=_optional_identity_attr(context.agent, "id"),
            agent_role=_optional_text_attr(context.agent, "role"),
            task_description=_optional_text_attr(context.task, "description"),
        )
        decision = provider.evaluate(request)
        if not isinstance(decision, CrewAIGuardrailDecision):
            raise TypeError("provider returned an invalid decision type")
        if not isinstance(decision.allow, bool):
            raise TypeError("decision.allow must be boolean")

        live_envelope = build_crewai_action_envelope(context, config)
        if canonical_action_envelope_v1_id(live_envelope) != action_id:
            return False
        return None if decision.allow else False
    except Exception:
        return False if config.fail_closed else None


def _snapshot_tool_input(value: Any) -> dict[str, Any]:
    """Copy the JSON-like CrewAI argument mapping before hashing."""

    if not isinstance(value, Mapping):
        raise TypeError("context.tool_input must be a mapping")
    return deepcopy(dict(value))


def _identity_ref(namespace: str, value: str) -> str:
    """Hash exact UTF-8 text to avoid lossy slug normalization."""

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{namespace}:sha256:{digest}"


def _required_text(value: Any, field_name: str) -> str:
    """Require one non-empty string without silent coercion."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_text_attr(source: Any, field_name: str) -> str | None:
    """Read one optional non-empty string attribute."""

    if source is None:
        return None
    value = getattr(source, field_name, None)
    return value if isinstance(value, str) and value else None


def _optional_identity_attr(source: Any, field_name: str) -> str | None:
    """Read one stable string or UUID identity attribute."""

    if source is None:
        return None
    value = getattr(source, field_name, None)
    if isinstance(value, str) and value:
        return value
    if isinstance(value, UUID):
        return str(value)
    return None
