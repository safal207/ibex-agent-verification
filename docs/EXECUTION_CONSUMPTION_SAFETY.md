# Execution Consumption Safety

## Status

This is a framework-neutral reference contract for classifying how far execution evidence reaches across the authorization-to-side-effect boundary. It does not persist grants, dispatch tools, or claim CrewAI core integration.

## Invariant: Authority follows atomicity

A component may claim grant-consumption authority only to the extent that it can atomically bind consumption to the commitment that causes dispatch, or the final side-effect endpoint enforces an equivalent occurrence-bound stable use token idempotently.

Authorization alone is not exclusive execution.

```text
historical validity
        ↓
current validity at use time
        ↓
execution binding
        ↓
consumption authority
        ↓
atomic consumption
        ↓
dispatch commitment
        ↓
actual side effect
        ↓
observed outcome
```

The layers answer different questions:

- **verification**: was the grant valid under the verified policy/evidence?
- **use-time revalidation**: is that authority still fresh now?
- **execution binding**: is the exact authorized action frozen for release?
- **consumption**: can only one competing execution claim the grant?
- **dispatch commitment**: is consumption atomic with the operation that causes dispatch?
- **outcome**: what was separately observed after the attempted side effect?

No earlier layer may silently stand in for a later one.

## Consumption modes

The closed v1 profile defines:

| Mode | Meaning | Maximum supported guarantee |
|---|---|---|
| `advisory_only` | state is checked or recorded separately from dispatch | `ADVISORY` |
| `local_atomic` | consumption and dispatch commitment share one local atomic boundary | `SINGLE_INSTANCE` |
| `shared_atomic` | competing executors share an atomic consumption/dispatch boundary | `ATOMIC` |
| `outbox_atomic` | consume and enqueue occur in the same atomic transaction; downstream delivery may still replay unless the final endpoint proves occurrence-bound idempotency | `ATOMIC_ENQUEUE`, or `IDEMPOTENT_ENDPOINT` with complete endpoint evidence |
| `tool_idempotent` | the final endpoint enforces an occurrence-bound stable use token | `IDEMPOTENT_ENDPOINT` |

### Local atomicity is deployment-scoped

`local_atomic` is `EXECUTION_SAFE` only for an explicitly `single_instance` executor scope. If two workers can independently consume the same grant using process-local state, replay protection across those workers is unproven.

### A shared ledger is not sufficient by itself

This sequence does **not** close the race:

```text
ledger.consume(grant)   # atomic inside ledger
        ↓
separate HTTP/tool dispatch
```

The consume operation and dispatch are still two operations. The profile therefore returns:

```text
NOT_EXECUTION_SAFE
DISPATCH_OUTSIDE_ATOMIC_BOUNDARY
```

A shared ledger closes the consume/enqueue gap when the ledger transaction also commits the dispatch trigger. An outbox proves one enqueue commitment, but it does not prove exclusive external execution: a worker can repeat delivery after the side effect succeeds but before its acknowledgement is recorded. Without occurrence-bound endpoint idempotency or equivalent delivery enforcement, `outbox_atomic` therefore returns:

```text
REPLAY_PROTECTION_UNPROVEN
ATOMIC_ENQUEUE
OUTBOX_DELIVERY_REPLAY_PROTECTION_UNPROVEN
```

When the same outbox record supplies a stable non-empty `use_token`, proves
that token is bound to the exact authorized occurrence, and states that the
final endpoint enforces it idempotently, the classifier can instead return
`EXECUTION_SAFE` with `IDEMPOTENT_ENDPOINT`. This is still a classification of
supplied evidence; it does not independently prove the endpoint implementation.

### Endpoint idempotency

When no shared transaction can span the external side effect, the final endpoint can own replay enforcement. `tool_idempotent` requires all three:

1. a stable non-empty `use_token`;
2. evidence that the token is bound to the exact authorized grant/occurrence (`use_token_bound: true`); and
3. explicit evidence that the endpoint enforces that token idempotently.

A caller-generated token that can differ per retry or per worker does not close the race: two competing executors could choose different keys and both side effects could succeed. Such a record returns `REPLAY_PROTECTION_UNPROVEN` with `USE_TOKEN_BINDING_UNPROVEN`.

A bound token without endpoint enforcement is also only advisory evidence. Enforcement without a token has nothing stable to deduplicate.

## Machine-readable record

```json
{
  "execution_binding": "external",
  "consumption_authority": "dispatch-ledger",
  "consumption_mode": "outbox_atomic",
  "executor_scope": "multi_instance",
  "dispatch_commitment_bound": true,
  "use_token": null,
  "use_token_bound": false,
  "endpoint_idempotency_enforced": false
}
```

The record is closed: missing and unknown fields fail rather than being guessed.

For an endpoint-owned replay boundary, a safe-shaped record instead requires:

```json
{
  "execution_binding": "external",
  "consumption_authority": "tool-endpoint",
  "consumption_mode": "tool_idempotent",
  "executor_scope": "multi_instance",
  "dispatch_commitment_bound": false,
  "use_token": "grant-42:occurrence-7",
  "use_token_bound": true,
  "endpoint_idempotency_enforced": true
}
```

## Verdicts

- `EXECUTION_SAFE`: the supplied evidence supports the mode-specific replay-safety claim.
- `REPLAY_PROTECTION_UNPROVEN`: some protection exists, but topology, token binding, or enforcement evidence does not support exclusive execution.
- `NOT_EXECUTION_SAFE`: the claimed atomic mechanism leaves dispatch outside the atomic boundary.
- `USE_TOKEN_REQUIRED`: endpoint-idempotency mode lacks the stable occurrence token needed for enforcement.

The result separately exposes a maximum guarantee:

- `NONE`
- `ADVISORY`
- `SINGLE_INSTANCE`
- `ATOMIC`
- `ATOMIC_ENQUEUE`
- `IDEMPOTENT_ENDPOINT`

## Conformance

Published vectors live in:

```text
conformance/execution-consumption-v1.json
```

They lock at least these boundaries:

1. advisory ledger check followed by separate dispatch → replay protection unproven;
2. local atomic single-instance execution → safe only within that instance scope;
3. local state with multiple workers → cross-instance replay protection unproven;
4. atomic shared-ledger consume followed by separate HTTP dispatch → not execution safe;
5. outbox consume + enqueue in one transaction → atomic enqueue, but external-delivery replay protection remains unproven;
6. outbox consume + enqueue with an occurrence-bound token and endpoint enforcement → execution safe at the idempotent endpoint;
7. endpoint idempotency without a use token → token required;
8. endpoint idempotency with an unbound caller-generated token → replay protection unproven;
9. endpoint idempotency with an occurrence-bound stable token and enforcement evidence → execution safe.

## Claim boundary

`verify_execution_safety()` is a deterministic classifier over supplied evidence. It does **not** prove that a database transaction, queue, token derivation, endpoint, or CrewAI runtime actually has the declared atomicity, binding, or idempotency properties. Those properties require separately captured implementation/runtime evidence.

Likewise, `EXECUTION_SAFE` does not prove that the side effect succeeded or produced the intended result. Outcome remains a separate observed record.

The intended proof chain is therefore:

```text
permission proof
  ≠ exclusive-use proof
  ≠ side-effect outcome proof
```

This separation is deliberate: verification proves permission; atomic consumption or occurrence-bound endpoint idempotency proves exclusive use within its stated scope; observed outcome proves what actually happened.
