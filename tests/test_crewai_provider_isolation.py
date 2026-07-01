"""CrewAI provider isolation tests."""

from types import SimpleNamespace
import unittest

from ibex_agent_verification.integrations.crewai import (
    CrewAIAdapterConfig,
    CrewAIGuardrailDecision,
    make_crewai_before_tool_call_hook,
)


class RecordingProvider:
    name = "recording"

    def __init__(self):
        self.request = None

    def evaluate(self, request):
        self.request = request
        return CrewAIGuardrailDecision(allow=True)


class CrewAIProviderIsolationTests(unittest.TestCase):
    def test_request_arguments_are_detached(self):
        context = SimpleNamespace(
            tool_name="calculate",
            tool_input={"value": 1},
            tool=SimpleNamespace(name="calculate"),
            agent=SimpleNamespace(role="Analyst"),
            task=None,
            crew=None,
        )
        provider = RecordingProvider()
        hook = make_crewai_before_tool_call_hook(
            provider,
            CrewAIAdapterConfig(
                resource_scope="workspace:demo",
                policy_version="policy-v1",
            ),
        )
        self.assertIsNone(hook(context))
        self.assertIsNot(provider.request.tool_input, context.tool_input)
        self.assertEqual(provider.request.tool_input, context.tool_input)


if __name__ == "__main__":
    unittest.main()
