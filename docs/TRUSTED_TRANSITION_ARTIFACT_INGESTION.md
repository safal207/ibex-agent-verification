# Trusted Transition Artifact Ingestion

This integration connects the existing production-source validator and trusted manifest signer to a real Ibex Verilator evidence artifact produced by GitHub Actions.

The chain proves that an exact pinned RTL simulation artifact was integrity-checked, promoted into a repository-bound GitHub Environment, transformed into the six-file transition-source contract, signed, and verified. It does not claim physical-hardware behavior, customer deployment, application correctness, or a production deployment.

## Live workflow chain

```text
Ibex Verilator E2E succeeds on main
  - checks out the verification project
  - builds the pinned lowRISC/ibex commit
  - runs Verilator and the hello firmware
  - parses architectural and timing evidence
  - verifies the evidence manifest
  - uploads ibex-verilator-evidence-{commit}
                    ↓
Ibex Evidence Promotion
  - runs only after the exact successful E2E workflow
  - enters the ibex-evidence-release GitHub Environment
  - selects one exact E2E artifact from the triggering run
  - downloads the raw ZIP and rechecks its GitHub SHA-256
  - safely extracts the archive
  - verifies every manifest-listed file and rejects extras
  - binds the project commit and pinned Ibex commit
  - checks simulator completion, firmware markers, parser status,
    causal enrichment, and full retirement alignment
  - emits the six-file production transition-source contract
  - validates that source with no signing authority
                    ↓
Trusted Transition Artifact Ingestion
  - runs only after the exact promotion workflow succeeds
  - selects and safely extracts the exact source artifact
  - validates repository, commit, run, workflow, environment,
    destination identity, release digest, and evidence consistency
  - builds manifest.json after source bytes are final
  - attests only manifest.json through GitHub OIDC
  - verifies online and bundled Sigstore evidence through ProofQA
  - audits and uploads the complete trust chain
  - publishes a non-authoritative discovery receipt
```

The deterministic `ProofQA Transition Source Artifact` reference workflow remains available for regression testing, but it no longer triggers the privileged signer.

## Real observation and claim boundary

The promoted subject is the exact GitHub Actions ZIP artifact produced by `Ibex Verilator E2E`. Its GitHub artifact SHA-256 becomes `release.subject_digest` throughout the transition evidence.

The observation requires:

- the exact successful `main` workflow run and attempt;
- the exact repository and head commit;
- the exact artifact name `ibex-verilator-evidence-{commit}`;
- the pinned lowRISC/ibex commit `022f084096baed0a9b5ebdf697ed2965f13e8ed8` as both requested and resolved ref;
- Verilator configuration `small` and the hello-test ELF;
- simulation exit code `0`;
- trace parser status `PARSED`;
- causal enrichment status `ENRICHED`;
- alignment ratio `1.0` with every retirement time matched;
- expected firmware and simulator-completion markers;
- an exact evidence manifest with no missing or additional files.

Timing-analyzer findings are preserved as evidence. Promotion does not reinterpret a detected timing anomaly as correctness or failure.

## Destination binding

The promotion job targets the GitHub Environment:

```text
ibex-evidence-release
```

The source evidence binds it to the platform-oriented identity:

```text
github-actions:repository-id:{repository_id}:environment:ibex-evidence-release
```

This is stronger than a free-text environment label because the repository numeric ID is part of the destination identity. Repository administrators may add required reviewers or deployment-branch rules to the GitHub Environment without changing the source contract.

## Permission boundary

`Ibex Evidence Promotion` receives only `contents: read` and `actions: read`. It can read the exact upstream artifact and publish a derived source artifact, but it cannot request an OIDC token, create an attestation, or sign its own evidence.

The privileged ingestion workflow receives OIDC and attestation permissions only after the exact promotion workflow succeeds. Pull-request validation remains read-only and cannot promote, sign, or publish receipts.

## Exact artifact selection

Both artifact boundaries require one and only one exact match. Selection binds:

- repository name and numeric repository ID;
- triggering run ID and run attempt;
- head repository ID;
- branch and exact commit SHA;
- workflow path recorded in the selection report;
- exact artifact name and numeric artifact ID;
- artifact API and archive URLs;
- non-expired state, size limit, and GitHub artifact SHA-256.

Missing, duplicated, expired, foreign, oversized, or inconsistently identified artifacts are rejected before policy evaluation.

## Raw download and safe extraction

Both downloads preserve the raw archive. The promotion and ingestion scripts independently rehash the archive before extraction.

Extraction rejects:

- absolute, parent-traversal, backslash, drive-like, and noncanonical paths;
- non-NFC names;
- duplicate and case-colliding paths;
- symbolic links and other non-regular entries;
- encrypted entries and unsupported compression methods;
- excessive entry counts, per-file sizes, and aggregate sizes;
- files outside the allowed E2E layout;
- files missing from or added beyond the evidence manifest;
- output directories that already exist or overlap the download directory.

Zero-byte log files are allowed only when their zero size and empty-file SHA-256 are explicitly listed in the upstream manifest.

## Signed source layout

The accepted transition source contains exactly:

```text
source-provenance.json
transition-report.json
evidence/intent.json
evidence/action.json
evidence/result.json
evidence/verification.json
```

The extracted source becomes `bundle/`. Manifest generation happens only after extraction and source validation complete.

Selection, extraction, promotion, source-validation, manifest-build, attestation, ProofQA, and audit reports remain outside `bundle/`. The verifier therefore cannot modify the bytes it is verifying.

## Receipt and authoritative evidence

Issue #42 is a mutable discovery ledger. The artifact-ingestion receipt binds:

- the exact E2E promotion source workflow, run, attempt, source artifact, and digest;
- the privileged signer workflow and run;
- the manifest, receipt, ProofQA report, and Sigstore bundle digests;
- the final signed trust-chain artifact and GitHub artifact digest;
- `VERIFIED` attestation and `PASS` ProofQA decision;
- the explicit non-production claim boundary.

The receipt comment is not cryptographic evidence. The authoritative records remain the GitHub artifact digests, source bytes, signed manifest, Sigstore bundle, verification reports, ProofQA report, and final audit.

## Remaining production step

A customer or service deployment can now replace `Ibex Evidence Promotion` while preserving the same downstream selector, safe extractor, source validator, manifest builder, signer restrictions, ProofQA verifier, audit, and receipt protocol.

Such an integration must supply a platform-bound destination oracle and a claim boundary appropriate to the actual deployment. The current Ibex integration deliberately stops at a real CI-hosted evidence release.
