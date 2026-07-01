"""Framework adapters for verifiable agent action identifiers."""

from ibex_agent_verification.integrations.crewai import (
    CrewAIAdapterConfig,
    CrewAIGuardrailDecision,
    CrewAIGuardrailProvider,
    CrewAIGuardrailRequest,
    build_crewai_action_envelope,
    make_crewai_before_tool_call_hook,
    register_crewai_guardrail,
)

__all__ = [
    "CrewAIAdapterConfig",
    "CrewAIGuardrailDecision",
    "CrewAIGuardrailProvider",
    "CrewAIGuardrailRequest",
    "build_crewai_action_envelope",
    "make_crewai_before_tool_call_hook",
    "register_crewai_guardrail",
]
