"""CrewAI hook registration for ActionEnvelopeV1 authorization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ibex_agent_verification.integrations.crewai_core import (
    CrewAIAdapterConfig,
    CrewAIGuardrailDecision,
    CrewAIGuardrailProvider,
    CrewAIGuardrailRequest,
    CrewAIToolCallContext,
    build_crewai_action_envelope,
    evaluate_crewai_tool_call,
)

CrewAIBeforeHook = Callable[[CrewAIToolCallContext], bool | None]
CrewAIHookRegistrar = Callable[[CrewAIBeforeHook], None]
CrewAIHookRegistryReader = Callable[[], list[Any]]


def make_crewai_before_tool_call_hook(
    provider: CrewAIGuardrailProvider,
    config: CrewAIAdapterConfig,
) -> CrewAIBeforeHook:
    """Create a hook matching CrewAI's False-blocks, None-allows contract."""

    def _hook(context: CrewAIToolCallContext) -> bool | None:
        return evaluate_crewai_tool_call(context, provider, config)

    return _hook


def register_crewai_guardrail(
    provider: CrewAIGuardrailProvider,
    config: CrewAIAdapterConfig,
    *,
    register_hook: CrewAIHookRegistrar | None = None,
    get_hooks: CrewAIHookRegistryReader | None = None,
) -> CrewAIBeforeHook:
    """Register authorization as the final CrewAI before-tool-call hook."""

    if (register_hook is None) != (get_hooks is None):
        raise ValueError("register_hook and get_hooks must be provided together")

    if register_hook is None or get_hooks is None:
        from crewai.hooks.tool_hooks import (
            get_before_tool_call_hooks,
            register_before_tool_call_hook,
        )

        register_hook = register_before_tool_call_hook
        get_hooks = get_before_tool_call_hooks

    authorize = make_crewai_before_tool_call_hook(provider, config)

    def _registered_hook(context: CrewAIToolCallContext) -> bool | None:
        try:
            hooks = get_hooks()
        except Exception:
            return False if config.fail_closed else None
        if not hooks or hooks[-1] is not _registered_hook:
            return False
        return authorize(context)

    register_hook(_registered_hook)
    return _registered_hook


__all__ = [
    "CrewAIAdapterConfig",
    "CrewAIGuardrailDecision",
    "CrewAIGuardrailProvider",
    "CrewAIGuardrailRequest",
    "CrewAIToolCallContext",
    "build_crewai_action_envelope",
    "evaluate_crewai_tool_call",
    "make_crewai_before_tool_call_hook",
    "register_crewai_guardrail",
]
