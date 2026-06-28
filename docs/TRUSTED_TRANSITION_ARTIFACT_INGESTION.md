# Trusted Transition Artifact Ingestion

This integration connects a real pinned Ibex Verilator run to a customer-consumable GitHub Release, observes the published bytes through the live release service, and only then signs the deployment evidence.

The chain proves integrity-preserving publication of one exact transition-source ZIP to a repository-bound public release destination. It does not claim that a customer installed or executed the asset, that physical hardware behaved correctly, that the application is correct, or that an independent human approved the deployment.

## Live workflow chain

```text
Ibex Verilator E2E succeeds on main
  - builds the pinned lowRISC/ibex commit
  - runs Verilator and the hello firmware
  - parses architectural and timing evidence
  - verifies the exact evidence manifest
  - uploads ibex-verilator-evidence-{commit}
                    ↓
Ibex Evidence Promotion
  - enters ibex-evidence-release
  - selects the exact E2E artifact and raw ZIP digest
  - safely extracts and verifies every manifest-listed file
  - binds the project commit and pinned Ibex commit
  - checks simulator completion, parser status, causal enrichment,
    and full retirement alignment
  - emits and validates the six-file staging transition source
  - has no signing authority
                    ↓
GitHub Release Production Deployment
  - enters ibex-customer-release
  - selects the exact promotion source from the triggering run
  - revalidates it before publication
  - creates or reuses the commit-specific public release
    ibex-evidence-{commit}
  - permits exactly one asset:
    proofqa-transition-source-{commit}.zip
  - refuses mutation when unexpected assets exist
  - downloads the published asset from the live release service
  - proves live bytes match the promoted source SHA-256
  - emits a new production transition source bound to repository ID,
    release ID, asset ID, tag, and digest
  - has no OIDC or attestation permission
                    ↓
Trusted Transition Artifact Ingestion
  - runs only after the exact release deployment succeeds
  - selects and safely extracts the exact production source artifact
  - independently fetches the public release through the GitHub API
  - compares live release and asset identity with source provenance
  - validates repository, commit, workflow, run, environment,
    destination identity, subject digest, and evidence consistency
  - builds manifest.json only after source bytes are final
  - attests only manifest.json through GitHub OIDC
  - verifies online and bundled Sigstore evidence through ProofQA
  - audits and uploads the complete trust chain
  - publishes a non-authoritative discovery receipt
```

The deterministic `ProofQA Transition Source Artifact` workflow remains available for regression testing, but it does not trigger the privileged signer.

## Real observations

### RTL evidence observation

The first observation requires:

- the exact successful `main` workflow run and attempt;
- the exact repository and head commit;
- artifact name `ibex-verilator-evidence-{commit}`;
- pinned lowRISC/ibex commit `022f084096baed0a9b5ebdf697ed2965f13e8ed8` as requested and resolved ref;
- Verilator configuration `small` and the hello-test ELF;
- simulation exit code `0`;
- trace parser status `PARSED`;
- causal enrichment status `ENRICHED`;
- alignment ratio `1.0` with every retirement time matched;
- expected firmware and simulator-completion markers;
- an exact evidence manifest with no missing or additional files.

Timing-analyzer findings are preserved as evidence. The workflow does not reinterpret a timing anomaly as correctness or failure.

### Customer release observation

The production oracle requires:

- tag `ibex-evidence-{commit}`;
- `target_commitish` equal to the exact 40-character source commit;
- a published, non-draft, non-prerelease release;
- canonical repository API and HTML URLs;
- exactly one asset named `proofqa-transition-source-{commit}.zip`;
- asset state `uploaded` and ZIP-compatible content type;
- canonical asset API and browser download URLs;
- the re-downloaded live asset size and SHA-256 equal to the promoted source archive;
- no unexpected release assets.

A rerun may reuse an exact existing release and asset, but it never overwrites or adds competing assets. Any inconsistent existing state blocks the workflow.

## Destination binding

The staging promotion uses:

```text
Environment: ibex-evidence-release
Identity: github-actions:repository-id:{repository_id}:environment:ibex-evidence-release
```

The customer release uses:

```text
Environment: ibex-customer-release
Identity: github-release:repository-id:{repository_id}:release-id:{release_id}:asset-id:{asset_id}:tag:ibex-evidence-{commit}
```

The production identity binds the stable numeric repository ID and the live release and asset IDs, not just a free-text environment label or URL.

Environment protection is tracked in issue #50. Until required reviewers and deployment-branch restrictions are configured, evidence must not claim independent human approval.

## Permission boundary

`Ibex Evidence Promotion` receives only `contents: read` and `actions: read`.

`GitHub Release Production Deployment` receives `contents: write` and `actions: read` so it can publish the exact public release asset. It cannot request an OIDC token or create an attestation.

`Trusted Transition Artifact Ingestion` receives OIDC and attestation permissions only after the live release deployment workflow succeeds and the signer independently observes the release API state.

Pull-request validation for all three workflows remains read-only and cannot promote, publish a release, sign, or publish receipts.

## Exact artifact selection

Every Actions artifact boundary requires exactly one match and binds:

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

Actions downloads preserve the raw archive. Each consumer independently rehashes the archive before extraction.

Extraction rejects:

- absolute, parent-traversal, backslash, drive-like, and noncanonical paths;
- non-NFC names;
- duplicate and case-colliding paths;
- symbolic links and other non-regular entries;
- encrypted entries and unsupported compression methods;
- excessive entry counts, per-file sizes, and aggregate sizes;
- files outside the allowed layout;
- missing or additional source files;
- output directories that already exist or overlap the download directory.

Zero-byte upstream evidence files are accepted only when their zero size and empty-file SHA-256 are explicitly listed in the upstream evidence manifest.

## Signed source layout

The accepted production transition source contains exactly:

```text
source-provenance.json
transition-report.json
evidence/intent.json
evidence/action.json
evidence/result.json
evidence/verification.json
```

The extracted source becomes `bundle/`. Manifest generation happens only after extraction, independent live release observation, and source validation complete.

Selection, extraction, release API responses, live observation, source validation, manifest build, attestation, ProofQA, and audit reports remain outside `bundle/`. The verifier therefore cannot modify the bytes it is verifying.

## Receipt and authoritative evidence

Issue #42 is a mutable discovery ledger. A successful artifact-ingestion receipt binds:

- the GitHub Release production source workflow, run, attempt, source artifact, and digest;
- the exact source commit;
- the privileged signer workflow and run;
- the manifest, receipt, ProofQA report, and Sigstore bundle digests;
- the final signed trust-chain artifact and GitHub artifact digest;
- `VERIFIED` attestation and `PASS` ProofQA decision;
- the explicit customer-release claim boundary.

The receipt comment is not cryptographic evidence. Authoritative records remain the GitHub artifact digests, public release and asset IDs, downloaded bytes, source evidence, signed manifest, Sigstore bundle, verification reports, ProofQA report, and final audit.

## Remaining external-production work

The GitHub Release adapter is a real public customer-delivery channel and a real platform oracle, but it is not an installation or runtime oracle.

A later adapter may observe a deployed service, device fleet, package registry, or customer environment. It should preserve the same exact-selector, safe-extractor, destination-oracle, source-validator, restricted-signer, ProofQA, audit, and receipt protocol while narrowing its claim to what the external platform can independently prove.
