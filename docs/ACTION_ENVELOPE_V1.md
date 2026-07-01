# ActionEnvelopeV1

`ActionEnvelopeV1` is the self-describing, cross-builder candidate profile for
freezing one tool-call authorization context before policy evaluation.

## Schema identity

Every V1 envelope includes the exact schema URI in `@context`:

```text
https://raw.githubusercontent.com/safal207/ibex-agent-verification/main/src/ibex_agent_verification/schemas/action-envelope-v1.schema.json
```

The same URI is the JSON Schema `$id`. Because `@context` is part of the
canonical preimage, changing the profile changes `action_id` and therefore
fails continuation matching.

## Locked fields

Required:

```text
@context
tool_identity
args_digest
caller_identity
resource_scope
policy_version
```

Optional and bound when present:

```text
authorization_deadline
```

Unknown fields fail closed.

## Canonical value profiles

- `tool_identity` is lowercase ASCII and may use `.`, `_`, `:`, `/`, or `-`.
- `args_digest` is `sha256:<64 lowercase hex>`.
- `caller_identity` and `resource_scope` are lowercase namespaced identifiers,
  such as `agent:qa` and `workspace:demo`.
- `policy_version` is a lowercase ASCII version token.
- `authorization_deadline`, when present, is UTC RFC 3339 at whole-second
  precision, for example `2026-07-01T05:00:00Z`.

These are rejection profiles rather than mutating normalizers. An adapter must
normalize values before constructing the envelope; the verifier does not guess
whether two differently spelled identities or timestamps are equivalent.

## Identifier

```text
action_id = SHA-256(JCS(ActionEnvelopeV1))
```

The restricted JCS profile is documented in
[`VERIFIABLE_ACTION_CHAIN.md`](VERIFIABLE_ACTION_CHAIN.md).

A machine-readable vector is published at:

```text
conformance/action-envelope-v1.json
```

Expected identifier for that vector:

```text
sha256:24d73b265e90f5a8bc4a2ff1b75e9f7f4eeafa4a3c4fce3cb9de839f3a458080
```

## Compatibility and migration

`canonical_action_envelope_v1_id()` is the strict V1 entry point.

`canonical_action_id()` also recognizes V1 when `@context` is present. It still
accepts the original unversioned action-envelope field set so the published
full-chain vector and existing adapters do not break during migration.

New adapters should emit and validate `ActionEnvelopeV1`. The unversioned path
is compatibility-only and should not be used as a new cross-implementation
contract.

## Explicit non-goals

V1 provides deterministic content integrity. It does not yet define:

- issuer signatures or key identifiers;
- nonce or replay domains;
- trusted clock/freshness policy;
- canonical JSON construction of the tool arguments before `args_digest`;
- maximum input size, nesting depth, or other resource-exhaustion limits.

Those layers remain separate so the envelope field set can stabilize before
authentication and replay policy are added.
