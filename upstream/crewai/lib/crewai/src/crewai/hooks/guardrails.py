from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from crewai.hooks.tool_hooks import (
    ToolCallHookContext,
    register_before_tool_call_hook,
)
from crewai.hooks.types import BeforeToolCallHookType


@dataclass(frozen=True, slots=True)
class GuardrailRequest:
    """Provider-agnostic context for one pre-tool-call authorization decision."""

    tool_name: str
    tool_alias: str
    tool_input: Mapping[str, Any]
    agent_id: str | None = None
    agent_role: str | None = None
    task_description: str | None = None
    crew_id: str | None = None


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    """Authorization verdict returned by a GuardrailProvider."""

    allow: bool
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class GuardrailProvider(Protocol):
    """Contract for pluggable pre-tool-call authorization providers."""

    name: str

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Evaluate whether the requested tool call should proceed."""
        ...


def enable_guardrail(
    provider: GuardrailProvider,
    *,
    fail_closed: bool = True,
) -> BeforeToolCallHookType:
    """Register a provider as a global before-tool-call authorization hook.

    Provider and request-construction failures block execution by default.
    Set ``fail_closed=False`` only when availability is more important than
    enforcing authorization.
    """

    def _hook(context: ToolCallHookContext) -> bool | None:
        try:
            request = _build_request(context)
            decision = provider.evaluate(request)
            if not isinstance(decision, GuardrailDecision):
                raise TypeError(
                    "GuardrailProvider.evaluate() must return GuardrailDecision"
                )
            if type(decision.allow) is not bool:
                raise TypeError("GuardrailDecision.allow must be a bool")
        except Exception:
            return False if fail_closed else None
        return None if decision.allow else False

    register_before_tool_call_hook(_hook)
    return _hook


def _build_request(context: ToolCallHookContext) -> GuardrailRequest:
    """Snapshot a mutable CrewAI hook context for provider evaluation."""

    original_tool_name = _optional_text(getattr(context, "tool", None), "name")
    return GuardrailRequest(
        tool_name=original_tool_name or context.tool_name,
        tool_alias=context.tool_name,
        tool_input=deepcopy(context.tool_input),
        agent_id=_optional_identifier(context.agent, "id"),
        agent_role=_optional_text(context.agent, "role"),
        task_description=_optional_text(context.task, "description"),
        crew_id=_optional_identifier(context.crew, "id"),
    )


def _optional_text(source: Any, attribute: str) -> str | None:
    """Read one optional non-empty text attribute."""

    if source is None:
        return None
    value = getattr(source, attribute, None)
    return value if isinstance(value, str) and value else None


def _optional_identifier(source: Any, attribute: str) -> str | None:
    """Read one optional identifier and normalize it to text."""

    if source is None:
        return None
    value = getattr(source, attribute, None)
    if value is None:
        return None
    rendered = str(value)
    return rendered if rendered else None
