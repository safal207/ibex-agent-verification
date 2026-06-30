# Crosswalk Contract Hardening v0.2

**Status:** Community draft follow-up to PR #61  
**Scope:** Runtime validation and comparison of `GuardrailDecision` records

## Why this follow-up exists

PR #61 fixed a real fail-open mismatch between the published schema field
`evidence_refs` and the runtime field `evidence_digest`. Independent review then
showed that field alignment alone was not enough: a hand-written partial
validator could still drift from the schema or accept two equally malformed
records as compatible.

The hardened rule is:

> A crosswalk may compare transition semantics only after both input records pass
> the same executable contract that the repository publishes.

## Executable schema

The runtime loads a packaged copy of
`schemas/guardrail-decision.schema.json` without adding a third-party runtime
dependency. A conformance test requires the public and packaged schema objects to
remain identical.

The dependency-free validator executes the schema keywords currently used by the
contract, including:

- object, array, string, number, integer, boolean, and null types;
- required and additional properties;
- constants and enumerations;
- item and string bounds;
- uniqueness;
- regular-expression patterns;
- numeric minimums;
- date-time formats;
- `allOf` and `if`/`then` conditionals.

## Evidence identity

Crosswalk evidence MUST be content-addressed:

```text
sha256:<64 lowercase hexadecimal characters>
```

A mutable URL or human-readable locator does not establish byte identity. Such a
locator may be carried elsewhere as metadata, but it cannot by itself prove that
two decisions were derived from the same evidence.

Runtime resource bounds are applied before allocation-heavy normalization:

- no more than 32 evidence references;
- no reference longer than 500 characters;
- no more than 4096 aggregate UTF-8 bytes;
- duplicate references are rejected.

## Crosswalk profile

A schema-valid `GuardrailDecision` is necessary but not sufficient for a
crosswalk. The crosswalk profile additionally requires non-empty string values
for:

- `claim_ceiling`;
- `permitted_next_transition`.

After schema and profile validation, compatibility requires equality of:

1. evidence bytes, represented by the content-addressed reference set;
2. `decision`;
3. normalized `allowed_runtime_use`;
4. `claim_ceiling`;
5. `permitted_next_transition`;
6. `trust_domain`.

Different taxonomy labels MAY remain compatible. Different authorization
outcomes, scopes, or transition rights MUST produce a collision.

## Result classes

### `INCOMPARABLE / INVALID_VERDICT_SHAPE`

At least one input violates the executable schema, crosswalk profile, or resource
bounds. Matching invalid values never become compatibility evidence.

### `INCOMPARABLE / EVIDENCE_MISMATCH`

Both inputs are valid, but they bind different evidence.

### `COLLISION / TRANSITION_SEMANTICS_MISMATCH`

Both inputs bind the same evidence but disagree on decision, runtime authority,
claim ceiling, next transition, or trust domain.

### `VALID / TRANSITION_SEMANTICS_PRESERVED`

Both inputs are valid, bind the same evidence, and preserve the complete compared
transition semantics.

## Decision-grant invariant

A `HARD_BLOCK` record may carry only `AUDIT_LOG` as runtime use. It cannot carry
an autonomous repair, retry, replanning, conformance, or certification grant.

This is the first conditional decision/grant invariant. A complete matrix for
all decision states remains future specification work.

## Review provenance

This follow-up incorporates:

- the independent recompute review and schema-drift warning from
  `babyblueviper1`;
- CodeRabbit's 500-character boundary finding and PR-description evidence
  checklist;
- contract, adversarial, systems, and resource-exhaustion review passes recorded
  on PR #61.

The review comments are design inputs. The executable schema and regression tests
are the source of truth.
