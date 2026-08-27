# Response Integrity Record v0.1

This profile extends ProofQA trusted-transition evidence with a separate,
manifest-bound record for claim-level response integrity.

It intentionally preserves the existing four transition evidence roles:

```text
intent_ref
action_ref
result_ref
verification_ref
```

`response_integrity_record` is not stored in `verification_ref` and does not
change the meaning of that role. Instead, it is passed to a second verifier and
must be listed in the same transition manifest as the transition report and the
captured result.

## Why a separate record

A transition may be correctly authorized and executed while the model reports a
false result. It may also be unauthorized but honestly reported. These states
must not be collapsed into one generic success or failure.

The combined receipt therefore exposes independent dimensions:

```text
authority = EXTERNAL_NOT_EVALUATED
execution = OBSERVED | NOT_OBSERVED
response_integrity = VERIFIED | FAILED | PARTIAL | NOT_EVALUATED
```

ProofQA does not issue authority in this profile. It verifies local evidence
binding and deterministic claim comparisons.

## Record fields

The schema is:

- [`schemas/proofqa-response-integrity-v0.1.schema.json`](../schemas/proofqa-response-integrity-v0.1.schema.json)

Each claim includes:

```text
claim_id
claim_text
claim_digest
observation_refs
comparison
verdict
reason_code
```

Portable claim verdicts are:

```text
SUPPORTED
CONTRADICTED
UNVERIFIABLE
OUT_OF_SCOPE
```

The verifier recomputes `claim_digest` and `response_digest` from explicit
profile-tagged preimages.

## Deterministic comparisons

v0.1 supports:

### `JSON_POINTER_EQUALS`

Loads one manifest-bound JSON observation, resolves a JSON Pointer, and compares
the observed value with `expected_value`.

### `REFERENCE_PRESENT`

Returns `SUPPORTED` only when all declared observation references exist in the
same manifest inventory. Missing references produce `UNVERIFIABLE`.

### `OUT_OF_SCOPE`

Marks a claim outside the declared evidence boundary without pretending it was
verified.

The declared claim verdict must equal the verdict derived by the comparison.

## Overall verdict

The overall response verdict is derived without hiding individual claims:

- any `CONTRADICTED` claim → `FAILED`;
- supported plus unverifiable claims → `PARTIAL`;
- only unverifiable claims → `FAILED`;
- only out-of-scope claims → `NOT_EVALUATED`;
- otherwise → `VERIFIED`.

## Manifest binding

The verifier first runs the existing transition-manifest verifier. It then
requires the response-integrity record itself to be:

- a regular non-symlink file;
- inside the evidence directory;
- listed in the same manifest;
- bound by canonical path, size, and SHA-256;
- distinct from the transition report.

Any post-manifest byte change fails closed before claim evaluation.

## Run

```bash
python scripts/proofqa_response_integrity.py \
  --evidence-dir evidence-bundle \
  --manifest evidence-bundle/manifest.json \
  --transition-report evidence-bundle/transition-report.json \
  --response-integrity evidence-bundle/evidence/response-integrity.json \
  --policy verify
```

## Conformance cases

The test corpus covers:

- exact supported result;
- plausible fabricated result;
- count drift;
- missing citation binding;
- mixed supported and unverifiable claims;
- declared verdict mismatch;
- tampered integrity bytes;
- backward compatibility with the original four-role bundle.

## Claim boundary

This profile proves local manifest binding and deterministic comparison of
explicit response claims against supplied local observations. It does not prove
policy correctness, signer identity, observation-source integrity, production
security, or action authorization.
