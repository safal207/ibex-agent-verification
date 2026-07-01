# CrewAI GuardrailProvider upstream patch kit

Prepared against CrewAI commit:

`1452ee2021b1ac1555c817bb83b59e30dd3ce9a8`

Related upstream issue: `crewAIInc/crewAI#4877`.

## File mapping

Copy the staged files into a fork of CrewAI:

- `upstream/crewai/lib/crewai/src/crewai/hooks/guardrails.py` to `lib/crewai/src/crewai/hooks/guardrails.py`
- `upstream/crewai/lib/crewai/src/crewai/hooks/__init__.py` to `lib/crewai/src/crewai/hooks/__init__.py`
- `upstream/crewai/lib/crewai/tests/hooks/test_guardrails.py` to `lib/crewai/tests/hooks/test_guardrails.py`

The staged `hooks/__init__.py` is a complete replacement based on the pinned CrewAI commit and should be rebased if upstream changes that file.

## Proposed scope

The patch adds only:

- `GuardrailRequest`
- `GuardrailDecision`
- `GuardrailProvider`
- `enable_guardrail()` over the existing `BeforeToolCallHook` registry

It intentionally excludes policy engines, RBAC, asynchronous suspension, signed audit records, configuration loading, and tool-execution pipeline changes.

## Safety behavior

- Provider and request-construction errors fail closed by default.
- `fail_closed=False` is an explicit availability-over-enforcement opt-out.
- Provider input is detached from CrewAI's mutable tool arguments.
- Invalid provider return types follow the same failure policy.
- The original tool-object name and sanitized alias are both available.
- Stable agent and crew identifiers are included when exposed by the runtime.

Suggested commit title: `feat: add GuardrailProvider pre-tool-call authorization`.
