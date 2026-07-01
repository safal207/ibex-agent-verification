"""CrewAI identity binding tests."""

from types import SimpleNamespace
import unittest

from ibex_agent_verification.action_chain import canonical_action_envelope_v1_id
from ibex_agent_verification.integrations.crewai import (
    CrewAIAdapterConfig,
    build_crewai_action_envelope,
)


class CrewAIIdentityBindingTests(unittest.TestCase):
    """Verify that runtime identities affect the action ID."""

    def setUp(self):
        self.context = SimpleNamespace(
            tool_name="calculate",
            tool_input={"value": 1},
            tool=SimpleNamespace(name="calculate"),
            agent=SimpleNamespace(role="Analyst"),
            task=None,
            crew=None,
        )
        self.config = CrewAIAdapterConfig(
            resource_scope="workspace:demo",
            policy_version="policy-v1",
        )

    def action_id(self):
        envelope = build_crewai_action_envelope(self.context, self.config)
        return canonical_action_envelope_v1_id(envelope)

    def test_original_tool_name_is_bound(self):
        baseline = self.action_id()
        self.context.tool.name = "Calculate"
        self.assertNotEqual(baseline, self.action_id())

    def test_stable_agent_key_is_preferred(self):
        role_only = self.action_id()
        self.context.agent.id = "stable-key"
        self.assertNotEqual(role_only, self.action_id())

    def test_empty_authorization_namespace_is_rejected(self):
        for config in (
            CrewAIAdapterConfig(resource_scope="", policy_version="policy-v1"),
            CrewAIAdapterConfig(resource_scope="workspace:demo", policy_version=""),
        ):
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, "non-empty string"):
                    build_crewai_action_envelope(self.context, config)


if __name__ == "__main__":
    unittest.main()
