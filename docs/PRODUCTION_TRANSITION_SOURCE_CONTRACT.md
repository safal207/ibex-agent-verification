# Production Transition Source Contract

This document defines the next integration boundary after the trusted post-CI transition manifest producer.

The existing producer already proves that one successful `main` commit can produce an exact manifest, receive a keyless GitHub OIDC attestation, pass online and bundled Sigstore verification, and be consumed by read-only ProofQA. The remaining gap is not signing. It is supplying real, final deployment evidence without weakening that trust boundary.

## Goal

A production integration must answer this question:

> Did the expected deployment workflow, for this exact repository commit and destination, produce these exact intention, action, result, and verification bytes before the trusted producer signed their manifest?

The production source adapter must replace only the reference-source assembly step. Manifest generation, signing, attestation verification, ProofQA evaluation, artifact publication, and receipt discovery remain separate stages.

## Trust boundaries

Three components have distinct responsibilities:

1. **Deployment evidence producer**
   - performs or observes the real deployment or promotion;
   - writes final evidence files;
   - has no ProofQA signing authority;
   - cannot declare its own evidence trusted.

2. **Trusted manifest producer**
   - runs only after the exact allowed deployment workflow succeeds;
   - checks repository, commit, workflow, run, destination, and artifact identity;
   - assembles an immutable local source directory;
   - builds the manifest after every source file is final;
   - signs only `manifest.json` through GitHub OIDC;
   - never edits the verified bundle after manifest creation.

3. **ProofQA verifier**
   - remains read-only;
   - verifies local bytes, online attestation, and the supplied Sigstore bundle;
   - returns `INVALID` before policy evaluation when integrity or identity checks fail;
   - never signs evidence it later verifies.

## Required source layout

The deployment workflow must publish one source artifact with this logical layout:

```text
production-transition-source/
├── source-provenance.json
├── transition-report.json
└── evidence/
    ├── intent.json
    ├── action.json
    ├── result.json
    └── verification.json
```

The source artifact must not contain:

- `manifest.json`;
- a Sigstore bundle;
- a ProofQA gate report;
- a manifest receipt;
- attestation verification reports;
- symlinks, device files, sockets, FIFOs, or unlisted nested artifacts.

Those are derived outputs and must be created outside the source directory.

## `source-provenance.json`

The provenance object is an input claim that the trusted producer must independently compare with GitHub event and artifact metadata. It is not trusted merely because it exists.

```json
{
  "schema_version": 1,
  "kind": "production-transition-source",
  "repository": "owner/repository",
  "source_commit": "40-lowercase-hex-sha",
  "deployment": {
    "workflow": ".github/workflows/deploy-production.yml",
    "run_id": 123456789,
    "run_attempt": 1,
    "event": "push",
    "branch": "main"
  },
  "destination": {
    "environment": "production",
    "identity": "platform-bound-destination-id"
  },
  "release": {
    "release_id": "immutable-release-id",
    "subject_digest": "sha256:<64-lowercase-hex>"
  },
  "claim_boundary": "Exact statement describing what this deployment evidence proves and does not prove."
}
```

## Required validation

Before copying any source bytes, the trusted producer must fail closed unless all conditions hold.

### Trigger identity

- trigger conclusion is `success`;
- trigger event is the allowed deployment event;
- trigger branch is `main` or another explicitly configured protected branch;
- trigger repository equals the current repository;
- trigger workflow equals the exact allowed deployment workflow;
- checked-out commit equals `workflow_run.head_sha`;
- the working tree is clean;
- persisted checkout credentials are disabled.

### Artifact identity

- the source artifact belongs to the triggering workflow run and run attempt;
- artifact name is exact, not prefix-matched;
- artifact ID and GitHub artifact digest are recorded outside the source bundle;
- foreign repository and foreign run URLs are rejected;
- expired, missing, duplicated, or ambiguously named artifacts are rejected;
- archive extraction rejects traversal paths, absolute paths, duplicate paths, links, and non-regular files.

### Provenance binding

The producer must compare `source-provenance.json` with trusted platform metadata:

- `repository` equals `github.repository`;
- `source_commit` equals the exact green deployment commit;
- deployment workflow, run ID, run attempt, event, and branch match the trigger;
- destination environment and identity match configured allowlists or platform-bound deployment metadata;
- release subject digest uses lowercase `sha256:<hex>` syntax;
- claim boundary is non-empty and is preserved in the final audit and receipt.

A free-text environment name alone is not sufficient destination identity.

### Evidence completeness

- all five required JSON files are regular files;
- every JSON document is an object;
- `transition-report.json` has status `VERIFIED`;
- intent, action, result, and verification references use canonical `manifest:<path>` form;
- every non-null evidence role resolves to a distinct local file;
- the transition ID, release identity, destination, and source commit are mutually consistent across evidence;
- post-deployment verification identifies the observed destination and the deployed subject digest;
- evidence files are final before manifest generation begins.

## Trusted producer sequence

```text
successful allowed deployment workflow
                  ↓
validate trigger repository/workflow/run/commit
                  ↓
download exact source artifact from that run
                  ↓
safely extract into a new immutable source directory
                  ↓
validate provenance and evidence consistency
                  ↓
copy final source files into the signing bundle
                  ↓
build deterministic manifest
                  ↓
verify every local path, size, and SHA-256
                  ↓
OIDC attestation of manifest.json only
                  ↓
preserve exact Sigstore bundle
                  ↓
ProofQA require-attested verification
  ├─ online verification
  └─ bundled verification
                  ↓
final structural audit
                  ↓
upload signed production trust chain
                  ↓
publish non-authoritative discovery receipt
```

## Output separation

The signed bundle contains only source material plus the generated manifest:

```text
bundle/
├── manifest.json
├── source-provenance.json
├── transition-report.json
└── evidence/
    ├── intent.json
    ├── action.json
    ├── result.json
    └── verification.json
```

All derived files remain outside `bundle/`:

```text
source-download.json
source-extraction.json
source-validation.json
manifest-build.json
pre-attestation-receipt.json
manifest.sigstore.json
manifest-receipt.json
manifest-receipt.json.attestation-online.json
manifest-receipt.json.attestation-bundled.json
proofqa-gate-report.json
final-audit.json
published-receipt.json
```

The verifier must never mutate the signed bundle while writing its own reports.

## Failure semantics

Integrity and identity failures are not policy decisions.

The producer or verifier must return `INVALID` and stop before ProofQA policy evaluation when any of these occur:

- one byte changes in a manifest-listed file;
- provenance disagrees with workflow metadata;
- the artifact came from another run or repository;
- the signer workflow is not exact;
- self-hosted signing or verification is detected where denied;
- destination identity is absent or inconsistent;
- deployment result or post-deployment verification is missing;
- derived output appears inside the signed bundle;
- evidence roles alias the same file;
- source files change after manifest generation.

On `INVALID`:

- no continuation receipt is created;
- no ProofQA gate report is created unless it is explicitly an integrity-failure report with no model/provider scoring;
- no model, provider, reliability, or latency statistics are updated;
- the failure is never represented as an ordinary `BLOCK`.

## Acceptance tests

The first implementation PR must cover at least these scenarios:

1. exact allowed production source produces `VERIFIED → PASS`;
2. one-byte evidence tampering is rejected before policy evaluation;
3. modified `transition-report.json` is rejected;
4. foreign repository artifact is rejected;
5. wrong deployment workflow is rejected;
6. mismatched commit, run ID, or run attempt is rejected;
7. missing or ambiguous artifact is rejected;
8. traversal path, symlink, duplicate archive path, and non-regular file are rejected;
9. missing destination identity is rejected;
10. destination or deployed subject digest mismatch is rejected;
11. signing by a different workflow is rejected;
12. self-hosted signer identity is rejected;
13. all verifier outputs remain outside the signed bundle;
14. the existing reference producer remains byte-for-byte reproducible and green.

## Replay and duplicate handling

A production receipt identity should be derived from this tuple:

```text
repository
+ source_commit
+ deployment workflow
+ deployment run ID
+ run attempt
+ destination identity
+ release subject digest
+ manifest digest
```

Publishing the same tuple twice may be treated as an idempotent replay. Reusing only part of the tuple for a different deployment must not be silently accepted.

The receipt ledger is a discovery index, not a cryptographic log. The GitHub artifact digest, signed manifest, Sigstore bundle, and verification reports remain authoritative.

## Implementation increments

### PR A — source contract and validator

- add a production-source validator and deterministic fixtures;
- validate provenance, paths, roles, destination identity, and cross-file consistency;
- keep all tests read-only and without OIDC permissions.

### PR B — trusted artifact ingestion

- trigger only from the exact allowed deployment workflow;
- download and safely extract the exact source artifact;
- bind artifact metadata to provenance;
- reuse the existing manifest, attestation, ProofQA, audit, and receipt stages.

### PR C — first real production integration

- connect one real protected deployment workflow;
- preserve the exact deployment subject and destination observation;
- run tampering and identity-negative tests;
- publish the first receipt whose claim boundary explicitly describes the real deployment observation.

## Non-goals

This contract does not claim that:

- a successful deployment proves application correctness;
- a hosted platform statement proves physical-world state;
- an attestation makes false evidence true;
- ProofQA replaces deployment authorization or human approval;
- an issue comment or receipt ledger is immutable evidence.

The chain proves origin, identity, ordering, and integrity of preserved evidence. The evidence still needs an appropriate oracle for the real property being claimed.
