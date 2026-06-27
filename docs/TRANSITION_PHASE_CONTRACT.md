# Transition Phase Contract

The Transition Phase Contract verifies one declared movement across three synchronized dimensions:

```text
Time:       t− → t0 → t+
Intention:  signal → declaration → commitment → action → verification
Space:      origin → boundary → destination
```

A transition is not accepted because an agent says that it changed state. The record must show when the intention existed, what concrete step was committed, which boundary was crossed, where the result was observed, and which evidence supports every claim.

## Phase loop

```text
CALIBRATE
   ↓
EXPAND
   ↓
COMMIT
   ↓
EXECUTE
   ↓
VERIFY
   ↓
REFLECT
   ↓
CONTINUE

Any contradiction, missed deadline, false destination, or claimed phase without its required evidence:

RECALIBRATE → CALIBRATE
```

The critical boundary is `EXPAND → COMMIT`.

Ideas, possibilities, and intentions may exist in `EXPAND`, but the transition does not enter `COMMIT` until all of these are explicit:

- declared intent identity and statement;
- concrete action;
- expected result;
- stopping condition;
- origin, boundary, and destination;
- pre-action intent evidence;
- commit timestamp.

This preserves the working rule:

> Expansion without a concrete step does not become execution. A claimed commitment without a concrete step returns to recalibration.

## Time axis

The time record uses one monotonic clock domain:

| Coordinate | Field | Meaning |
|---|---|---|
| `t−` | `observed_before_ns` | observed state before transition |
| intent | `intent_declared_ns` | intention existed before commitment |
| `t0` | `commit_ns` | concrete transition commitment |
| execution | `action_started_ns` | committed action began |
| `t+` | `result_observed_ns` | result was observed |
| evaluation | `evaluated_ns` | record evaluation point |
| deadline | `deadline_ns` | optional transition deadline |

Timestamps may not move backward. Execution cannot precede commitment, commitment cannot precede declared intention, and result observation cannot precede execution.

A result observed after the deadline causes `RECALIBRATE`. An unfinished transition evaluated after its deadline also causes `RECALIBRATE`.

## Intention axis

The contract does not infer hidden intent from an action or result.

A complete declaration requires:

```text
intent_id
statement
intent_declared_ns
intent_ref
```

A complete commitment additionally requires:

```text
action
expected_result
stopping_condition
commit_ns
boundary
destination
```

A timestamp alone cannot create a commitment. If `commit_ns` exists while the concrete commitment is incomplete, the report records:

```text
commit_without_concrete_step
```

and moves to `RECALIBRATE`.

## Space axis

Space is a named execution or state context, not necessarily a physical location.

Examples:

```text
mobile.checkout.submitting
mobile.payment.success/731
agent.plan.draft
agent.plan.approved
repository.pull-request
repository.main
```

A transition requires:

- `origin` — the last evidenced context;
- `boundary` — the explicit boundary crossed;
- `destination` — the claimed new context;
- `destination_observed: true` — independent confirmation that the destination was reached.

`origin` and `destination` must differ. The contract never fabricates presence in a destination merely because an action was attempted.

## Evidence references

The record carries opaque references instead of embedding unrestricted evidence:

```text
intent_ref
action_ref
result_ref
verification_ref
```

They may point to hashes, traces, assertions, manifest entries, or other durable evidence. This validator checks completeness and consistency of the references; outer evidence verification remains a separate responsibility.

## Statuses

| Status | Meaning |
|---|---|
| `IN_PROGRESS` | current phase is valid but later evidence is not available yet |
| `VERIFIED` | time, intention, and space all converge with positive verification |
| `RECALIBRATE` | a semantic claim lacks evidence, the deadline was missed, or observed verification contradicts the commitment |

Malformed records return CLI exit code `2` and are not converted into `RECALIBRATE`.

## CLI

```bash
ibex-av verify-transition-phase \
  --record examples/transition-phase/payment-recovery-verified.json \
  --report /tmp/payment-recovery-transition-report.json
```

Exit codes:

| Exit | Meaning |
|---:|---|
| `0` | `VERIFIED` |
| `1` | `IN_PROGRESS` |
| `2` | invalid or contradictory input schema/chronology |
| `3` | `RECALIBRATE` |

The report path must differ from the source record, preventing the verifier from overwriting the evidence it evaluates.

## Example result

```json
{
  "status": "VERIFIED",
  "phase": "REFLECT",
  "next_phase": "CONTINUE",
  "axes": {
    "time": {"status": "PASS"},
    "intention": {"status": "PASS"},
    "space": {"status": "PASS"}
  }
}
```

## Invariants

1. Intention must be evidenced before commitment.
2. Commitment must contain a concrete action, expected result, and stopping condition.
3. Execution must not occur before commitment.
4. Result observation must not occur before execution.
5. A destination must differ from the origin and be independently observed.
6. A missed deadline cannot be converted into success by later narration.
7. A partial phase claim triggers recalibration instead of synthetic continuity.
8. Verification does not infer hidden intention or fabricate external-world change.

## Relationship to ProofQA

ProofQA already separates correctness, completion, provider reliability, and time performance. The Transition Phase Contract adds a different kind of evidence: whether an agent's claimed movement from one state or context to another is chronologically valid, intentionally committed, spatially evidenced, and safe to continue.

It is intentionally not reduced to a blended percentage. A transition is a structured state change with explicit reasons for `IN_PROGRESS`, `VERIFIED`, or `RECALIBRATE`.

A later increment can let ProofQA Release Gate consume a transition report alongside the scorecard and require `VERIFIED` before deployment or autonomous continuation.
