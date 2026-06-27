# Trusted Transition Manifest Producer

The trusted transition manifest producer is the privileged counterpart to the read-only ProofQA verifier.

It answers a narrow question:

> Did one successful push to `main`, already accepted by the ProofQA workflow, produce this exact transition manifest through the expected hosted GitHub workflow identity?

## Trust boundary

Pull requests never receive signing permissions. They run only the `validate` job with `contents: read`.

The privileged `produce` job runs only when all conditions are true:

```text
trigger workflow: ProofQA Release Gate Action
trigger conclusion: success
trigger event: push
trigger branch: main
trigger repository: this repository
checkout commit: exact workflow_run.head_sha
```

The checkout disables persisted credentials and verifies that `git rev-parse HEAD` equals the triggering green commit before assembling evidence.

## Producer sequence

```text
successful ProofQA push run on main
              ↓
checkout exact green commit
              ↓
assemble final transition source
              ↓
write honest producer provenance
              ↓
build deterministic manifest after source is final
              ↓
verify every path, size, and SHA-256 locally
              ↓
keyless OIDC attestation of manifest.json only
              ↓
preserve Sigstore bundle
              ↓
ProofQA require-attested verification
  ├─ online GitHub attestation lookup
  └─ supplied Sigstore bundle verification
              ↓
final structural audit
              ↓
upload complete signed reference trust chain
```

The allowed signer identity is exact:

```text
safal207/ibex-agent-verification/.github/workflows/trusted-transition-manifest.yml
```

Self-hosted runners are denied during verification.

## Why the manifest is built after CI

The producer does not sign a manually maintained list of expected hashes. It assembles the final source files, writes commit-bound provenance, and then builds `manifest.json` from the resulting directory.

The deterministic builder:

- rejects symlinks and non-regular paths;
- requires canonical manifest references;
- requires the transition report itself in the inventory;
- verifies that every non-null evidence role resolves to a distinct file;
- records exact byte size and SHA-256;
- immediately re-runs the strict manifest verifier.

Only after those checks does the signing step receive the manifest.

## Reference claim boundary

The first producer input is the committed ProofQA transition fixture. Its provenance states explicitly:

```text
This signed reference bundle verifies the trusted post-CI producer path.
It is not a production deployment claim.
```

This proves the signing and verification architecture without pretending that a real customer deployment occurred.

## Artifact contents

The uploaded reference artifact contains:

```text
bundle/
  manifest.json
  producer-provenance.json
  transition-report.json
  evidence/
    intent.json
    action.json
    result.json
    verification.json
assembly.json
manifest-build.json
pre-attestation-receipt.json
manifest.sigstore.json
manifest-receipt.json
manifest-receipt.json.attestation-online.json
manifest-receipt.json.attestation-bundled.json
proofqa-gate-report.json
final-audit.json
```

The signed subject is `bundle/manifest.json`. The final ProofQA report binds the manifest digest, transition report digest, evidence-role inventory, attestation repository, signer workflow, and verification-report digests.

## Moving from reference to production

A production integration should replace only the source assembly step. It should collect real final evidence such as:

- approved release intention;
- exact deployment or promotion action;
- immutable build and deployment result;
- post-deployment verification result;
- environment and destination identity;
- the verified transition report.

The security rules should remain unchanged:

1. no signing on pull requests;
2. exact successful `main` commit checkout;
3. manifest generated after evidence is final;
4. exact hosted signer workflow;
5. online and bundled verification;
6. explicit claim boundary;
7. read-only consumer verification through ProofQA.

The producer proves origin and integrity of the preserved evidence. It does not independently prove that every statement inside an evidence file is true in the physical world.
