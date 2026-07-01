"""CrewAI adapter conformance tests."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from ibex_agent_verification.action_chain import canonical_action_envelope_v1_id
from ibex_agent_verification.integrations.crewai import (
    CrewAIAdapterConfig,
    CrewAIGuardrailDecision,
    build_crewai_action_envelope,
    make_crewai_before_tool_call_hook,
    register_crewai_guardrail,
)

VECTOR = Path(__file__).resolve().parents[1] / "conformance" / (
    "crewai-action-envelope-v1.json"
)


class Provider:
    """Record requests and return a configured decision."""

    name = "test"

    def __init__(self, allow=True, callback=None):
        """Configure the decision and an optional evaluation callback."""

        self.allow = allow
        self.callback = callback
        self.requests = []

    def evaluate(self, request):
        """Record one request, run the callback, and return the decision."""

        self.requests.append(request)
        if self.callback:
            self.callback(request)
        return CrewAIGuardrailDecision(allow=self.allow)


class CrewAIAdapterTests(unittest.TestCase):
    """Verify deterministic IDs and fail-closed behavior."""

    def setUp(self):
        """Build a structural CrewAI context from the published vector."""

        self.vector = json.loads(VECTOR.read_text(encoding="utf-8"))
        source = self.vector["hook_context"]
        self.context = SimpleNamespace(
            tool_name=source["tool_name"],
            tool_input=dict(source["tool_input"]),
            tool=SimpleNamespace(name=source["tool_name"]),
            agent=SimpleNamespace(role=source["agent_role"]),
            task=SimpleNamespace(description="test task"),
            crew=None,
        )
        cfg = self.vector["adapter_config"]
        self.config = CrewAIAdapterConfig(**cfg)

    def test_vector_recomputes(self):
        """The adapter must reproduce the published action identifier."""

        envelope = build_crewai_action_envelope(self.context, self.config)
        self.assertEqual(
            canonical_action_envelope_v1_id(envelope),
            self.vector["action_id"],
        )

    def test_allow_and_deny(self):
        """Provider decisions must map to CrewAI allow and block semantics."""

        allow = Provider(True)
        self.assertIsNone(
            make_crewai_before_tool_call_hook(allow, self.config)(self.context)
        )
        self.assertEqual(allow.requests[0].action_id, self.vector["action_id"])
        deny = Provider(False)
        self.assertIs(
            make_crewai_before_tool_call_hook(deny, self.config)(self.context),
            False,
        )

    def test_live_argument_drift_blocks(self):
        """Arguments changed during evaluation must invalidate authorization."""

        def mutate(_request):
            """Change the live CrewAI argument mapping during evaluation."""

            self.context.tool_input["recipient"] = "other"

        hook = make_crewai_before_tool_call_hook(
            Provider(True, mutate),
            self.config,
        )
        self.assertIs(hook(self.context), False)

    def test_unsupported_number_fails_closed(self):
        """Unsupported floats must block unless fail-open is explicit."""

        self.context.tool_input["temperature"] = 0.5
        closed = make_crewai_before_tool_call_hook(Provider(), self.config)
        self.assertIs(closed(self.context), False)
        open_config = CrewAIAdapterConfig(
            resource_scope="workspace:demo",
            policy_version="policy-v1",
            fail_closed=False,
        )
        opened = make_crewai_before_tool_call_hook(Provider(), open_config)
        self.assertIsNone(opened(self.context))

    def test_registered_hook_must_remain_last(self):
        """Registration-order drift must block the tool call."""

        hooks = []
        hook = register_crewai_guardrail(
            Provider(),
            self.config,
            register_hook=hooks.append,
            get_hooks=lambda: list(hooks),
        )
        self.assertIsNone(hook(self.context))
        hooks.append(lambda _context: None)
        self.assertIs(hook(self.context), False)

    def test_registry_read_failure_respects_policy(self):
        """Registry errors must block by default and open only by opt-out."""

        def broken_registry():
            """Simulate CrewAI registry API failure."""

            raise RuntimeError("registry unavailable")

        hooks = []
        closed = register_crewai_guardrail(
            Provider(),
            self.config,
            register_hook=hooks.append,
            get_hooks=broken_registry,
        )
        self.assertIs(closed(self.context), False)

        open_config = CrewAIAdapterConfig(
            resource_scope="workspace:demo",
            policy_version="policy-v1",
            fail_closed=False,
        )
        opened = register_crewai_guardrail(
            Provider(),
            open_config,
            register_hook=hooks.append,
            get_hooks=broken_registry,
        )
        self.assertIsNone(opened(self.context))


if __name__ == "__main__":
    unittest.main()
