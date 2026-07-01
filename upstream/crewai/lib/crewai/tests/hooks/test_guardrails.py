from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest

from crewai.hooks import (
    GuardrailDecision,
    GuardrailRequest,
    clear_before_tool_call_hooks,
    enable_guardrail,
    get_before_tool_call_hooks,
)
from crewai.hooks.tool_hooks import ToolCallHookContext


class RecordingProvider:
    """Small provider fixture that records the latest request."""

    name = "recording"

    def __init__(
        self,
        decision: GuardrailDecision | None = None,
        error: Exception | None = None,
    ) -> None:
        self.decision = decision or GuardrailDecision(allow=True)
        self.error = error
        self.request: GuardrailRequest | None = None

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Record the request and return the configured result."""

        self.request = request
        if self.error is not None:
            raise self.error
        return self.decision


@pytest.fixture(autouse=True)
def clear_hooks() -> None:
    """Keep the global before-hook registry isolated between tests."""

    clear_before_tool_call_hooks()
    yield
    clear_before_tool_call_hooks()


@pytest.fixture
def context() -> ToolCallHookContext:
    """Build one representative CrewAI tool-call context."""

    tool = Mock()
    tool.name = "Send Email"
    agent = Mock()
    agent.id = "agent-123"
    agent.role = "Support Agent"
    task = Mock()
    task.description = "Reply to the customer"
    crew = Mock()
    crew.id = "crew-456"
    return ToolCallHookContext(
        tool_name="send_email",
        tool_input={"recipient": "qa@example.com", "body": "Hello"},
        tool=tool,
        agent=agent,
        task=task,
        crew=crew,
    )


def test_enable_guardrail_registers_and_allows(
    context: ToolCallHookContext,
) -> None:
    """An allow decision registers one hook and permits execution."""

    provider = RecordingProvider()
    hook = enable_guardrail(provider)

    assert get_before_tool_call_hooks() == [hook]
    assert hook(context) is None
    assert provider.request is not None
    assert provider.request.tool_name == "Send Email"
    assert provider.request.tool_alias == "send_email"
    assert provider.request.agent_id == "agent-123"
    assert provider.request.agent_role == "Support Agent"
    assert provider.request.task_description == "Reply to the customer"
    assert provider.request.crew_id == "crew-456"


def test_deny_decision_blocks(context: ToolCallHookContext) -> None:
    """A provider deny decision maps to CrewAI's False hook result."""

    provider = RecordingProvider(GuardrailDecision(allow=False, reason="policy"))
    hook = enable_guardrail(provider)

    assert hook(context) is False


def test_provider_receives_detached_tool_input(
    context: ToolCallHookContext,
) -> None:
    """Provider-side mutation cannot change CrewAI's live tool arguments."""

    provider = RecordingProvider()
    hook = enable_guardrail(provider)
    assert hook(context) is None
    assert provider.request is not None

    provider.request.tool_input["recipient"] = "other@example.com"

    assert context.tool_input["recipient"] == "qa@example.com"


def test_provider_failure_is_fail_closed_by_default(
    context: ToolCallHookContext,
) -> None:
    """Provider failures block execution unless fail-open is explicit."""

    provider = RecordingProvider(error=RuntimeError("unavailable"))

    assert enable_guardrail(provider)(context) is False


def test_provider_failure_can_fail_open(
    context: ToolCallHookContext,
) -> None:
    """The caller may explicitly prioritize availability over enforcement."""

    provider = RecordingProvider(error=RuntimeError("unavailable"))

    assert enable_guardrail(provider, fail_closed=False)(context) is None


@pytest.mark.parametrize("fail_closed, expected", [(True, False), (False, None)])
def test_invalid_provider_result_follows_failure_policy(
    context: ToolCallHookContext,
    fail_closed: bool,
    expected: bool | None,
) -> None:
    """Invalid provider results follow the same configured failure policy."""

    provider = RecordingProvider()
    provider.decision = object()  # type: ignore[assignment]

    assert enable_guardrail(provider, fail_closed=fail_closed)(context) is expected


def test_decision_is_frozen() -> None:
    """Decision records are immutable value objects."""

    decision = GuardrailDecision(allow=True)

    with pytest.raises(AttributeError):
        decision.allow = False  # type: ignore[misc]

    assert replace(decision, allow=False).allow is False
