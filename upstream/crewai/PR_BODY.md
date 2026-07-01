## Summary

Add a small provider-agnostic contract for pre-tool-call authorization on top of CrewAI's existing hook system.

Closes crewAIInc/crewAI#4877.

## Changes

- add `GuardrailRequest`, `GuardrailDecision`, and `GuardrailProvider`;
- add `enable_guardrail()` as a thin adapter over `BeforeToolCallHook`;
- export the new API from `crewai.hooks`;
- add tests for allow, deny, fail-closed, fail-open, detached tool input, invalid provider results, and immutable decisions.

## Compatibility

This does not change the tool execution pipeline or existing hook behavior. Providers are optional and register through the current global before-tool-call registry.

## Safety defaults

Provider failures and invalid results block execution by default. Callers may explicitly set `fail_closed=False` to preserve availability instead.

## Out of scope

- bundled policy engines;
- RBAC;
- asynchronous suspend/resume;
- signed audit records;
- YAML provider loading;
- changes to task guardrails.
