# CrewAI ActionEnvelopeV1 adapter

This adapter turns CrewAI's existing `BeforeToolCallHook` context into a strict
`ActionEnvelopeV1` before a tool is allowed to execute.

The reference CrewAI API inspected for the conformance vector is commit:

```text
1452ee2021b1ac1555c817bb83b59e30dd3ce9a8
```

## Mapping

```text
ToolCallHookContext.tool.name
  -> SHA-256(exact UTF-8)
  -> tool_identity

ToolCallHookContext.tool_input
  -> restricted JCS
  -> args_digest

ToolCallHookContext.agent.id
  -> SHA-256(exact stable identity)
  -> caller_identity

configured resource scope + policy version
  -> ActionEnvelopeV1
  -> action_id
```

CrewAI passes a sanitized `context.tool_name` to hooks. The adapter keeps that
value in the provider request for diagnostics, but binds `context.tool.name`
when available so different original tool names cannot collapse to the same
sanitized identity.

CrewAI's frozen agent UUID is preferred for `caller_identity`. When no stable
agent ID is exposed by a compatible context, the adapter hashes the exact role
string as a compatibility fallback. An absent agent uses the explicit anonymous
identity.

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

The published vector intentionally exercises the role fallback so builders that
do not expose CrewAI model objects can still reproduce it. Runtime CrewAI
contexts should bind the frozen agent ID when available.

Expected action identifier:

```text
sha256:b6ed48d2dfc400f860b42b4ef3d46d1ca1e8eb362d249f252817448a892ef59d
```

## Current boundary

This is a synchronous `ALLOW` / `DENY` adapter over CrewAI's existing hook
contract. It does not yet add framework-level `DEFER` / resume, result binding,
or audit persistence. Those require lifecycle support beyond a hook that only
returns `bool | None`.
