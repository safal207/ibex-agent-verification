# CrewAI ActionEnvelopeV1 adapter

This adapter turns CrewAI's existing `BeforeToolCallHook` context into a strict
`ActionEnvelopeV1` before a tool is allowed to execute.

The reference CrewAI API inspected for the conformance vector is commit:

```text
1452ee2021b1ac1555c817bb83b59e30dd3ce9a8
```

## Mapping

```text
ToolCallHookContext.tool_name
  -> SHA-256(exact UTF-8)
  -> tool_identity

ToolCallHookContext.tool_input
  -> restricted JCS
  -> args_digest

ToolCallHookContext.agent.role
  -> SHA-256(exact UTF-8)
  -> caller_identity

configured resource scope + policy version
  -> ActionEnvelopeV1
  -> action_id
```

Exact text is hashed instead of slugged by this adapter. That avoids collisions
where different role or tool strings normalize to the same spelling.

## Hook behavior

CrewAI uses these return values for before-tool-call hooks:

- `False`: block execution;
- `True` or `None`: allow execution.

`make_crewai_before_tool_call_hook()` maps a provider decision to that contract.
Adapter, canonicalization, and provider errors return `False` by default. A
caller may explicitly configure `fail_closed=False`, but that weakens the
authorization boundary.

The provider receives copies of the envelope and tool arguments. After provider
evaluation, the adapter rebuilds the live envelope and blocks if the action ID
changed.

## Registration order

CrewAI permits before hooks to mutate `tool_input` in place and executes hooks in
registration order. Authorization must therefore be the final before hook, or a
later hook could change arguments after approval.

`register_crewai_guardrail()` appends the adapter and checks its registry
position on every invocation. If another hook was registered after it, the call
is blocked rather than authorizing stale arguments.

```python
from ibex_agent_verification.integrations.crewai import (
    CrewAIAdapterConfig,
    register_crewai_guardrail,
)

register_crewai_guardrail(
    provider,
    CrewAIAdapterConfig(
        resource_scope="workspace:production",
        policy_version="policy-v1",
    ),
)
```

## Conformance vector

The published fixture is:

```text
conformance/crewai-action-envelope-v1.json
```

Expected action identifier:

```text
sha256:b6ed48d2dfc400f860b42b4ef3d46d1ca1e8eb362d249f252817448a892ef59d
```

## Current boundary

This is a synchronous `ALLOW` / `DENY` adapter over CrewAI's existing hook
contract. It does not yet add framework-level `DEFER` / resume, result binding,
or audit persistence. Those require lifecycle support beyond a hook that only
returns `bool | None`.
