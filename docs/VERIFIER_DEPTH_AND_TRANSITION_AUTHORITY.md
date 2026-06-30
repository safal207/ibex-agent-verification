# Verifier Depth and Transition Authority

**Draft Specification v0.1**  
**Author:** Aleksey Safonov (`@safal207`)  
**Status:** Community draft  
**Scope:** Agent tool-call governance, decision verification, autonomous repair, retry, and replanning

## Abstract

Agent frameworks increasingly use guardrails to determine whether an agent may invoke a tool, modify state, access data, or continue an autonomous workflow.

Most guardrail interfaces focus on the verdict: allow, deny, defer, or retry. That is insufficient. A verdict may exist without being independently verifiable, and an autonomous agent must not receive more authority than the evidence supporting that verdict can justify.

This specification introduces **Verifier Depth**: a classification describing how far a guardrail decision can be independently recomputed.

> Verifier depth is not audit decoration. It is the authority boundary of the next transition.

The core runtime invariant is:

> **No autonomous next transition may exceed the verifier depth that supports it.**

This document defines:

1. verifier-depth levels D0-D3;
2. permitted runtime use for each level;
3. a structured `GuardrailDecision` shape;
4. authorization-to-outcome binding;
5. continuation safety;
6. recomputable taxonomy crosswalks;
7. minimum conformance tests.

## Normative language

The terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** describe normative requirements.

## 1. Problem statement

A binary guardrail result collapses materially different situations into the same answer:

- malformed arguments;
- wrong tool selection;
- expired authorization;
- unavailable policy provider;
- privacy or tenant-boundary violation;
- missing approval;
- stochastic semantic score;
- independently reproducible decision.

The orchestrator needs to know whether it may repair, retry, replan, defer, escalate, or only log the verdict.

A second problem is trust. A signed decision can be tamper-evident while still being impossible to recompute.

Tamper evidence proves:

> The record has not changed since it was signed.

Recomputability proves:

> An independent party can derive the same relevant decision from stable source inputs and declared comparison rules.

These properties compose, but they are not equivalent.

## 2. Core concepts

### 2.1 Transition

A **transition** is any autonomous state change selected or initiated by an agent, including:

- invoking a tool;
- modifying external data;
- sending a message;
- executing code;
- changing a plan;
- retrying an operation;
- escalating to another agent;
- publishing a conformance claim.

### 2.2 Authorization record

An `authorization_record` represents the decision made before execution. It SHOULD bind:

- caller or agent identity;
- tool identity;
- canonical arguments or argument digest;
- resource, tenant, and workspace scope;
- policy version;
- evidence references;
- issued time and expiration;
- decision;
- verifier depth;
- permitted runtime use.

### 2.3 Observation record

An `observation_record` represents what actually happened during execution. It SHOULD contain:

- stable `tool_call_id`;
- execution identity;
- result reference or result digest;
- exit state;
- observation time;
- source class or observation vantage;
- capture profile;
- observer identity and attestation, when available.

### 2.4 Response-integrity record

A `response_integrity_record` represents whether the model described the tool result honestly. It SHOULD bind individual claims to observation records.

Suggested verdicts are:

- `SUPPORTED`;
- `CONTRADICTED`;
- `UNVERIFIABLE`;
- `MIXED`.

Pre-execution authorization and post-execution claim integrity are separate controls. Neither replaces the other.

## 3. Verifier-depth model

### D0 - Attested only

The producer reports a verdict, score, or explanation, but an independent party cannot reproduce the base decision step.

Examples:

- a signed deny without the policy snapshot;
- an LLM semantic score without stable scorer binding;
- a provider assertion with no portable recomputation path.

Permitted runtime use:

- `AUDIT_LOG`;
- human review;
- informational reporting.

A D0 verdict MUST NOT independently authorize autonomous repair, retry, or replanning.

### D1 - Provider-pinned verification

The decision binds the verifier or scorer to a declared identity or immutable version. The record SHOULD include:

- provider identity;
- scorer or model identifier;
- snapshot or reproducible fingerprint;
- canonical inputs;
- threshold and score;
- policy version;
- trust-domain disclosure.

The implementation may remain proprietary. The binding prevents silent scorer migration but may still require trusting the provider.

Permitted runtime use:

- `BOUNDED_RETRY`;
- `LOW_RISK_REPAIR`;
- approval-gated remediation;
- scorer-migration warnings.

D1 MUST NOT authorize high-impact autonomous transitions solely on its own.

### D2 - Independently reproducible verification

An independent auditor, registry, or checker can reproduce the relevant decision against the same pinned inputs, policy, and verifier snapshot.

The producer's own grader is insufficient by itself when independence is claimed.

Permitted runtime use:

- `STRUCTURED_REPLAN`;
- `CONTROLLED_AUTONOMOUS_RETRY`;
- bounded autonomous repair;
- controlled escalation inside the declared trust domain.

D2 does not automatically imply that the entire scorer is public.

### D3 - Publicly reproducible verification

The full relevant decision path is publicly reproducible, including, where applicable:

- inputs;
- canonicalization rules;
- policy;
- thresholds;
- decision logic;
- scorer implementation or reproducible equivalent;
- public test vectors.

Permitted runtime use:

- `PUBLIC_CONFORMANCE`;
- `EXTERNAL_CERTIFICATION`;
- cross-implementation benchmarking;
- high-authority transitions explicitly granted by policy.

D3 does not mean infallible. It means publicly inspectable and reproducible.

## 4. Runtime authority rule

Every autonomous action SHOULD declare a minimum verifier depth.

```python
REQUIRED_DEPTH = {
    "AUDIT_LOG": "D0",
    "BOUNDED_RETRY": "D1",
    "LOW_RISK_REPAIR": "D1",
    "STRUCTURED_REPLAN": "D2",
    "CONTROLLED_AUTONOMOUS_RETRY": "D2",
    "PUBLIC_CONFORMANCE": "D3",
    "EXTERNAL_CERTIFICATION": "D3",
}
```

Before execution, the runtime MUST enforce both conditions:

```text
verifier_depth >= required_depth(proposed_transition)
```

and:

```text
proposed_transition in allowed_runtime_use
```

If either condition fails, the transition MUST fail closed.

A runtime MUST NOT infer authority merely from:

- a positive verdict;
- a signature;
- a trusted brand;
- a human-readable explanation;
- a matching taxonomy label.

A verdict may be correct while lacking sufficient depth to authorize the next action.

## 5. Decision states

A provider SHOULD return a structured state rather than only `allow: bool`.

### `ALLOW`

The proposed action may execute under the attached scope and policy.

### `REPAIR`

The submitted action MUST NOT execute unchanged, but the orchestrator MAY perform an explicitly bounded correction.

Examples include adding a missing parameter, normalizing an argument, or selecting a compatible tool.

### `SOFT_BLOCK`

The action MUST NOT execute yet. It MAY be retried after remediation such as credential refresh, approval, context update, budget refresh, or backoff.

### `HARD_BLOCK`

The action MUST NOT be retried automatically. Typical causes include tenant-boundary violations, prohibited data access, legal restrictions, or irreversible unsafe state changes.

### `DEFER`

The decision is pending external resolution. A continuation token identifies one frozen authorization context and MUST NOT act as broad permission for a later modified action.

## 6. Guardrail decision fields

The machine-readable schema is located at:

[`schemas/guardrail-decision.schema.json`](../schemas/guardrail-decision.schema.json)

Core fields include:

- `decision_id`;
- `tool_call_id`;
- `decision`;
- `reason_code`;
- `failure_class`;
- `violated_boundary`;
- `severity`;
- `retry_policy`;
- `suggested_replan_constraint`;
- `required_remediation`;
- `policy_version`;
- `verifier_depth`;
- `allowed_runtime_use`;
- `trust_domain`;
- `recompute_mode`;
- `evidence_refs`;
- `action_id`;
- `issued_at` and `expires_at`.

## 7. Fail-closed requirements

A provider adapter SHOULD default to `fail_closed = True`.

When fail-closed mode is enabled, the following MUST prevent execution:

- provider initialization failure;
- provider timeout or transport failure;
- failed health check;
- malformed response;
- invalid signature;
- expired decision;
- missing or unknown verifier depth;
- missing policy version;
- action-envelope mismatch;
- continuation replay;
- continuation reuse with modified arguments;
- missing required evidence.

A guardrail MUST NOT silently degrade into an ungoverned execution path.

## 8. Authorization-to-outcome binding

A stable `tool_call_id` MUST bind:

1. the proposed tool call;
2. the authorization decision;
3. the actual execution;
4. the observation record;
5. the model's later claim about the result.

```text
authorization_record.tool_call_id
        ==
observation_record.tool_call_id
        ==
response_integrity_record.tool_call_id
```

A signed decision record alone is insufficient.

> A tool call is governed when authorization, execution outcome, and audit evidence preserve the same recomputable transition boundary.

## 9. Continuation safety

A deferred authorization MUST freeze the action context before returning control to the agent.

The envelope SHOULD bind:

- tool identity;
- canonical argument digest;
- caller identity;
- resource scope;
- policy version.

```text
action_id = H(
    tool_identity,
    args_digest,
    caller_identity,
    resource_scope,
    policy_version
)
```

Resume MUST succeed only when the pending action exactly matches the frozen context.

A change to arguments, tool, caller, resource scope, tenant, or policy version MUST create a new authorization decision.

An unchanged retry SHOULD be idempotent. An expired or consumed continuation MUST fail closed.

## 10. Stochastic verifiers

Semantic scorers, embeddings, and model-based judges may be stochastic or provider-controlled.

A stochastic verifier SHOULD bind:

- model identifier;
- snapshot or fingerprint;
- exact inputs;
- normalization method;
- threshold;
- observed score;
- observed jitter or tolerance;
- decision rule.

A verdict can remain reproducible even when a floating-point score is not bit-identical, provided the decision margin exceeds observed jitter:

```text
abs(score - threshold) > observed_jitter
```

If the margin does not exceed declared jitter, the verdict SHOULD be classified as partial or depth-bounded.

The system MUST NOT claim stronger reproducibility than the scorer binding supports.

## 11. Learning without historical drift

Adaptive guardrails MUST NOT silently mutate behavior through hidden accumulated state.

A policy update SHOULD create a new immutable version:

```text
policy_v2 = g(
    policy_v1,
    joined_outcome_dataset,
    selection_profile,
    calibration_code_version
)
```

The derivation SHOULD bind the source dataset digest, inclusion and exclusion rules, time window, filtering rules, code version, previous policy version, and resulting policy digest.

Historical decisions MUST remain reproducible under the policy version that originally produced them.

> Learning changes the future without falsifying the past.

## 12. Taxonomy crosswalks

Different systems MAY use different names for equivalent verifier levels.

Interoperability MUST NOT be determined by label similarity. A mapping is valid only when both systems preserve the same:

- evidence basis;
- `allowed_runtime_use`;
- `claim_ceiling`;
- `permitted_next_transition`;
- trust domain, where relevant.

```text
same evidence
+
same allowed_runtime_use
+
same claim_ceiling
+
same permitted_next_transition
=
valid crosswalk
```

### Vocabulary collision

If two systems use the same label but authorize different runtime behavior, the mapping MUST fail closed.

### Different labels, same authority

If two systems use different labels but preserve the same authority tuple, they MAY be operationally compatible.

### Recomputable mapping

A crosswalk is itself a claim. It MUST expose a recomputation path from both source verdicts. A third party SHOULD derive both authority tuples and fail closed on divergence.

A mapping that cannot be recomputed is a naming agreement, not a conformance proof.

## 13. Minimum conformance tests

An implementation claiming compatibility SHOULD test at least:

1. D0 allows audit only when explicitly granted.
2. D0 cannot trigger autonomous replanning.
3. D1 can perform bounded low-risk repair.
4. D1 cannot publish public conformance.
5. D2 can trigger structured replanning inside its trust domain.
6. D3 can support public conformance when explicitly granted.
7. Missing depth fails closed.
8. Unknown depth fails closed.
9. Sufficient depth without an explicit runtime grant still fails closed.
10. Unknown transition type fails closed.
11. Equivalent action envelopes produce the same action ID.
12. Changed arguments invalidate a continuation.
13. Changed policy version invalidates a continuation.
14. Unchanged action context resumes successfully.
15. Different labels with the same authority tuple pass crosswalk validation.
16. Matching labels with different authority fail closed as a collision.
17. Crosswalks over different evidence are incomparable.

Executable reference tests live in [`tests/test_verifier_depth.py`](../tests/test_verifier_depth.py).

## 14. Economic considerations

Structured decisions can reduce repeated invalid calls, blind retries, debugging time, rollback cost, audit cost, compliance exposure, and silent correctness failures.

Estimated gain SHOULD be discounted by verifier confidence:

```text
adjusted_gain =
estimated_cost_avoided
× verifier_confidence_factor
- cost_of_delay
```

Economic value does not override authority constraints. A high-value D0 denial MUST NOT receive the same autonomous authority as an equivalent D2 or D3 decision.

## 15. Non-goals

This specification does not:

- prescribe one policy engine;
- prescribe one agent framework;
- require a blockchain;
- require public weights for every verifier;
- guarantee that a reproducible policy is ethically correct;
- replace human review in high-risk domains;
- certify CrewAI or any current provider implementation;
- require identical vocabulary across frameworks.

The goal is narrower:

> Make the authority of guardrail decisions explicit, bounded, and testable.

## 16. Primary invariants

1. **No autonomous next transition may exceed the verifier depth that supports it.**
2. **A tool call is governed only when authorization, execution outcome, and audit evidence preserve the same action identity and transition boundary.**
3. **A signed decision may be tamper-evident without being independently recomputable.**
4. **Learning must change future policy without changing the recorded meaning of past decisions.**
5. **A standard begins when independent systems preserve the same transition boundary, even when their vocabulary differs.**
6. **Every validator that maps another validator must expose a recomputation path for that mapping.**

## Closing principle

A guardrail verdict is not sufficient merely because it exists, is signed, or comes from a trusted provider.

Its runtime authority must be limited by the strength of the verification supporting it.

The operational question is:

> **What is the agent safely authorized to do next, based on how independently this decision can be checked?**

That question turns guardrails from passive safety documentation into active transition-governance infrastructure.
