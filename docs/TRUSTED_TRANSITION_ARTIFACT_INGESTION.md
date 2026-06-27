# Trusted Transition Artifact Ingestion

This increment connects the existing production-source validator to a real cross-workflow GitHub Actions artifact boundary.

It remains a reference trust-path demonstration. It does not claim that a customer or production deployment occurred.

## Workflow chain

```text
ProofQA Release Gate Action succeeds on main
                    ↓
ProofQA Transition Source Artifact
  - checks out the exact green commit
  - builds six final reference source files
  - validates them with no signing permission
  - uploads one exact source artifact
                    ↓
Trusted Transition Artifact Ingestion
  - runs only after the exact source workflow succeeds
  - selects exactly one artifact from that run
  - binds repository, repository IDs, run, attempt, branch, and commit
  - downloads the raw ZIP with digest mismatch configured as an error
  - safely extracts only the six allowed source files
  - runs the production-source validator
  - builds the manifest after source bytes are final
  - attests only manifest.json through GitHub OIDC
  - verifies online and bundled attestation evidence through ProofQA
  - audits and uploads the complete trust chain
```

## Permission boundary

The source workflow has only `contents: read`. It cannot request an OIDC token, create an attestation, or sign the artifact it publishes.

The privileged ingestion workflow receives `actions: read` only so it can query and download the artifact belonging to its exact triggering run. Signing permissions exist only in its post-source `produce` job. Pull-request validation remains read-only.

## Exact artifact selection

The selector requires one and only one matching artifact. It binds:

- repository name and numeric repository ID;
- triggering workflow run ID and run attempt;
- head repository ID;
- head branch and exact commit SHA;
- exact artifact name and numeric artifact ID;
- artifact API and archive URLs;
- non-expired state, size limit, and GitHub artifact SHA-256 digest.

Missing, duplicated, expired, foreign, oversized, or inconsistently identified artifacts are rejected before download or policy evaluation.

## Raw download and safe extraction

The download action is pinned to a full commit SHA and instructed to preserve the raw archive. The ingestion script independently rehashes that archive before extraction.

Extraction rejects:

- absolute, parent-traversal, backslash, drive-like, and noncanonical paths;
- non-NFC names;
- duplicate and case-colliding paths;
- symbolic links and other non-regular entries;
- encrypted entries and unsupported compression methods;
- excessive entry counts, per-file sizes, and aggregate uncompressed sizes;
- missing or additional source files;
- output directories that already exist or overlap the download directory.

The accepted archive contains exactly:

```text
source-provenance.json
transition-report.json
evidence/intent.json
evidence/action.json
evidence/result.json
evidence/verification.json
```

## Output separation

The extracted source becomes `bundle/`. Manifest generation happens only after extraction and source validation complete.

Selection, extraction, validation, manifest-build, attestation, ProofQA, and audit reports remain outside `bundle/`. The verifier therefore cannot modify the bytes it is verifying.

## Claim boundary

The first end-to-end run signs a reference source whose destination is `proofqa:trusted-artifact-ingestion`. It proves that an exact artifact can cross a workflow boundary and remain bound to its repository, run identity, commit, bytes, manifest, signer, and ProofQA decision.

It does not prove a production deployment, general application correctness, or physical-world state.

## Next production increment

A real integration should replace the reference source builder with one protected deployment workflow that emits the same six-file contract. The selector, raw download, safe extraction, validator, manifest builder, signer restrictions, attestation verification, and read-only ProofQA consumer should remain unchanged.
