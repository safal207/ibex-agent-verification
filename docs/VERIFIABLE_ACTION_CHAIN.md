# Verifiable Action Chain

> `⟦#⛓✓⟧` is the compact, non-normative symbol for a frozen, canonically
> hashed, cryptographically linked, verified action record.

The normative linkage is:

```text
action_envelope
    │ canonical_action_id()
    ↓
action_id ───────────────┐
                         │ canonical_decision_id()
evidence_refs ───────────┤
authority fields ────────┘
                         ↓
                    decision_id
                         ↓
              execution_outcome_id
                         ↓
                  audit_record_id
```

`evidence_refs` are **not** part of `action_id`. They first enter the canonical
preimage at the `decision_id` stage, where they are bound together with the
frozen action identifier and the decision authority surface.

Every downstream record **MUST** bind to the identifier of the exact upstream
record it consumes.

## Canonicalization profile

Contract identifiers use a restricted RFC 8785-compatible JSON
Canonicalization Scheme (JCS) profile:

- object keys are ordered by UTF-16 code units;
- strings are serialized as JSON and encoded as UTF-8;
- arrays preserve order unless the contract explicitly defines them as sets;
- booleans and `null` use their JSON spellings;
- integers are limited to the interoperable IEEE-754 safe range;
- floating-point values, lone UTF-16 surrogates, non-string object keys, and
  non-JSON Python values are rejected.

The restricted numeric profile keeps the package dependency-free without
claiming a general implementation of every RFC 8785 number edge case.
Identifier preimages should use strings and content-addressed digests wherever
possible.

## Action identifier

The action envelope has a locked field set.

Required fields:

```text
tool_identity
args_digest
caller_identity
resource_scope
policy_version
```

Optional bound field:

```text
authorization_deadline
```

The identifier is:

```text
action_id = SHA-256(JCS(action_envelope))
```

Unknown envelope fields fail closed. An adapter must not silently add an
unbound field that could drift between `DEFER` and resume.

Resume invariant:

> The action resumed after `DEFER` must reproduce the same frozen `action_id`.
> Otherwise authorization fails closed and a new decision is required.

## Decision identifier

`decision_id` binds the action identifier, evidence, and decision authority
surface:

```text
action_id
schema_version
decision
reason_code
policy_version
verifier_depth
allowed_runtime_use
trust_domain
claim_ceiling
permitted_next_transition
evidence_refs
issued_at
expires_at (optional)
```

`allowed_runtime_use` and `evidence_refs` are semantic sets and are sorted
before canonicalization. Duplicates fail closed.

The identifier is:

```text
decision_id = SHA-256(JCS({
  action_id,
  evidence_refs,
  authority fields...
}))
```

Human-facing labels and local `tool_call_id` values are deliberately excluded
from the authority digest. The executable schema remains responsible for the
complete decision-record shape.

## Outcome and audit links

A downstream link is computed from:

```text
record_type
upstream_id
payload_ref
```

where both identifiers are strict `sha256:<64 lowercase hex>` references:

```text
record_id = SHA-256(JCS({
  record_type,
  upstream_id,
  payload_ref
}))
```

This permits:

```text
decision_id
  → execution_outcome_id
  → audit_record_id
```

without requiring a shared database. Each verifier can independently
recompute the same identifiers from the same canonical bytes.

## Conformance vector

Action envelope:

```json
{
  "tool_identity": "send_email",
  "args_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "caller_identity": "agent:qa",
  "resource_scope": "workspace:demo",
  "policy_version": "policy-v1"
}
```

Canonical UTF-8 JSON:

```json
{"args_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","caller_identity":"agent:qa","policy_version":"policy-v1","resource_scope":"workspace:demo","tool_identity":"send_email"}
```

Expected identifier:

```text
sha256:5efc8759c0a4fb5ab9b33a1a0d8b9ca69d123eaac8d6c643e7a271906ce1b11d
```

## Adapter policy boundary

The core authorization layer treats insufficient verifier depth as
fail-closed:

```text
INSUFFICIENT_VERIFIER_DEPTH
```

An orchestrator adapter may translate that result into `DEFER` plus an
escalation request. That translation is adapter policy, not a universal core
semantic.

## Cross-implementation alignment

Independent implementations may converge on the construction
`SHA-256(JCS(...))` while still producing different identifiers for the same
logical action. JCS removes differences in object-key ordering; it does not
remove differences in:

- field names or field sets;
- value types;
- timestamp representation;
- namespace or identity normalization;
- omitted versus explicit optional values.

For example, `timestamp_ms` encoded as an integer and `timestamp` encoded as an
ISO-8601 string are different preimages and therefore **MUST** produce different
hashes.

The current interoperability status is therefore:

```text
canonicalization construction: aligned in principle
locked cross-builder preimage: pending
cross-builder identifier equality: unclaimed
```

Compatibility becomes demonstrated only when every builder consumes the exact
same published preimage — identical field names, values, value types, and
optional-field rules — and reproduces the same canonical bytes and digest.
This contract's locked action-envelope field set is the candidate convergence
surface; external systems remain non-conformant until they pass its vectors
byte-for-byte.
