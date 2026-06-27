# ProofQA Release Gate GitHub Action

ProofQA converts one deterministic QA scorecard, an optional Transition Phase Contract report, and optional manifest-bound transition evidence into:

```text
PASS
WARN
BLOCK
```

The gate keeps independent concerns separate:

- end-to-end score;
- answer correctness;
- completion reliability;
- provider reliability;
- client-observed time;
- transition readiness across time, intention, and space;
- integrity and signer identity of transition evidence.

Evidence integrity is never blended into model-quality percentages. Modified evidence is invalid input, not a low model score.

## Basic usage

```yaml
- name: Evaluate AI QA release evidence
  id: proofqa
  uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
  with:
    summary-path: artifacts/qa-benchmark/summary.json
    transition-report-path: artifacts/release-transition-report.json
    transition-policy: require-verified
    policy-name: mobile-production
    min-answer-correctness: "95"
    min-completion-reliability: "95"
    min-provider-reliability: "99"
    max-p95-duration-ms: "2000"
    fail-on: block
    report-path: artifacts/proofqa-gate-report.json
```

Pin the action to a full commit SHA.

## Transition policy

| Mode | Transition report | Effect |
|---|---|---|
| `ignore` | not required | transition finding disabled |
| `warn` | required | unfinished or recalibrating transition produces `WARN` |
| `require-verified` | required | only a structurally consistent `VERIFIED` transition passes |

A `VERIFIED` label alone is insufficient. ProofQA also requires:

```text
phase: REFLECT
next_phase: CONTINUE
issues: []
time.status: PASS
intention.status: PASS
space.status: PASS
```

The preflight requires phase-appropriate evidence depth:

```text
EXPAND  → intent_ref
EXECUTE → intent_ref + action_ref
VERIFY  → intent_ref + action_ref + result_ref
REFLECT → intent_ref + action_ref + result_ref + verification_ref
```

`IN_PROGRESS` cannot contain issues or a blocked axis. `RECALIBRATE` must return to `CALIBRATE` and contain an issue or blocked axis.

## Transition manifest policy

`transition-manifest-policy` adds byte-level evidence binding.

| Mode | Manifest | Attestation | Effect |
|---|---|---|---|
| `ignore` | not required | not required | backward-compatible transition behavior |
| `verify` | required | not required | verifies exact local inventory and canonical refs |
| `require-attested` | required | required | additionally verifies signer identity online and from a supplied Sigstore bundle |

A manifest-enabled transition report uses canonical references:

```json
{
  "evidence": {
    "intent_ref": "manifest:evidence/intent.json",
    "action_ref": "manifest:evidence/action.json",
    "result_ref": "manifest:evidence/result.json",
    "verification_ref": "manifest:evidence/verification.json"
  }
}
```

The transition report itself must also be listed in the same manifest. This closes the substitution gap where evidence files could stay unchanged while the report pointing to them was replaced.

Each manifest entry contains exactly:

```json
{
  "path": "evidence/result.json",
  "size_bytes": 82,
  "sha256": "<64 lowercase hexadecimal characters>"
}
```

Strict verification rejects:

- absolute, non-canonical, backslash, `.` or `..` paths;
- duplicate manifest entries;
- missing, modified, symlinked, escaping, or unlisted files;
- a manifest listing itself;
- a transition report absent from the inventory;
- refs without the `manifest:` scheme;
- refs to files absent from the inventory;
- one file reused for multiple evidence roles;
- a receipt whose transition digest no longer matches the consumed report.

### Verified local manifest

```yaml
permissions:
  contents: read

steps:
  - uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
    with:
      summary-path: artifacts/qa-benchmark/summary.json
      transition-report-path: artifacts/transition-bundle/transition-report.json
      transition-policy: require-verified
      transition-manifest-policy: verify
      transition-evidence-dir: artifacts/transition-bundle
      transition-manifest-path: artifacts/transition-bundle/manifest.json
      transition-manifest-receipt-path: artifacts/transition-manifest-receipt.json
      report-path: artifacts/proofqa-gate-report.json
```

### Attested manifest

```yaml
permissions:
  contents: read
  attestations: read

steps:
  - uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
    with:
      summary-path: artifacts/qa-benchmark/summary.json
      transition-report-path: artifacts/transition-bundle/transition-report.json
      transition-policy: require-verified
      transition-manifest-policy: require-attested
      transition-evidence-dir: artifacts/transition-bundle
      transition-manifest-path: artifacts/transition-bundle/manifest.json
      transition-manifest-receipt-path: artifacts/transition-manifest-receipt.json
      transition-attestation-bundle-path: artifacts/transition-manifest.sigstore.json
      transition-attestation-repository: owner/repository
      transition-attestation-signer-workflow: owner/repository/.github/workflows/transition-evidence.yml
      report-path: artifacts/proofqa-gate-report.json
```

The action runs both forms of verification:

```text
gh attestation verify manifest.json --repo ... --signer-workflow ... --deny-self-hosted-runners
gh attestation verify manifest.json --repo ... --signer-workflow ... --deny-self-hosted-runners --bundle ...
```

Both commands must succeed. Their JSON reports and the Sigstore bundle are hashed into the transition-manifest receipt.

`require-attested` verifies an existing attestation; it does not mint one. The trusted producer workflow should create the manifest only after its evidence is final, attest that exact manifest with OIDC, preserve the bundle, and publish both without modification.

## Time policy

Scorecard v3 derives time from monotonic timestamps inside preserved inference captures. It excludes job queue time, SDK installation, cooldowns, and unrelated workflow work.

For an enabled time policy:

1. p95 above `max-p95-duration-ms` produces `BLOCK`;
2. p95 inside the configured warning band produces `WARN`;
3. p95 below the band produces `PASS`;
4. missing p95 follows `unknown-metric-policy`.

Set `max-p95-duration-ms: "0"` to disable time gating and preserve scorecard v2 compatibility.

## Workflow enforcement

| `fail-on` | Behavior |
|---|---|
| `never` | emits decision and reports without failing |
| `block` | only `BLOCK` fails |
| `warn` | `WARN` and `BLOCK` fail |

## Inputs

| Input | Default | Meaning |
|---|---:|---|
| `summary-path` | required | scorecard v2 or v3 summary |
| `transition-report-path` | empty | Transition Phase Contract report |
| `transition-policy` | `ignore` | `ignore`, `warn`, or `require-verified` |
| `transition-manifest-policy` | `ignore` | `ignore`, `verify`, or `require-attested` |
| `transition-evidence-dir` | empty | exact bundle root |
| `transition-manifest-path` | empty | manifest inside the bundle root |
| `transition-manifest-receipt-path` | `proofqa-transition-manifest-receipt.json` | local integrity and attestation receipt |
| `transition-attestation-bundle-path` | empty | Sigstore bundle for the manifest |
| `transition-attestation-repository` | current repository | expected attestation owner/repository |
| `transition-attestation-signer-workflow` | empty | exact allowed signer workflow identity |
| `policy-name` | `default` | policy identity stored in reports |
| `min-end-to-end` | `90` | minimum end-to-end percentage |
| `min-answer-correctness` | `90` | minimum completed-answer correctness |
| `min-completion-reliability` | `95` | minimum valid-completion percentage |
| `min-provider-reliability` | `95` | minimum provider success percentage |
| `warn-margin` | `3` | percentage warning band |
| `max-p95-duration-ms` | `0` | maximum successful-request p95 |
| `time-warn-margin-ms` | `250` | time warning band |
| `unknown-metric-policy` | `block` | `block`, `warn`, or `ignore` |
| `fail-on` | `block` | `block`, `warn`, or `never` |
| `report-path` | `proofqa-gate-report.json` | final machine-readable report |

## Outputs

Alongside the scorecard and transition outputs, the action exposes:

| Output | Example |
|---|---|
| `transition-manifest-status` | `VERIFIED` or `n/a` |
| `transition-manifest-sha256` | manifest SHA-256 or `n/a` |
| `transition-manifest-receipt-sha256` | receipt SHA-256 or `n/a` |
| `transition-attestation-status` | `VERIFIED`, `NOT_REQUIRED`, or `n/a` |

## Gate report v4

The final report binds:

- scorecard source path and SHA-256;
- transition report identity and SHA-256;
- transition-manifest receipt path and SHA-256;
- manifest path, SHA-256, and file count;
- all four role-to-file bindings with path, size, and SHA-256;
- attestation repository, exact signer workflow, bundle digest, and online/bundled verification-report digests when required;
- independent policy findings and the final decision.

A transition integrity failure occurs before policy evaluation and therefore does not create a normal gate report. This prevents corrupted evidence from being represented as an ordinary `BLOCK` result.

## Security boundary

The action requests no write permission and never calls `actions/attest`. It only verifies already-produced evidence. `require-attested` uses the current GitHub token for read-only attestation lookup; callers must grant `attestations: read`.

The local manifest verifier proves exact bytes in the supplied directory. The attestation verifier proves that the manifest bytes were signed by the explicitly allowed hosted workflow identity. Neither claim proves that the real world changed beyond the contents of the supplied evidence files.

Stable quality and latency claims still require repeated, versioned runs, controlled environments, sample-size disclosure, and trend analysis.

## Next increments

1. create a trusted post-CI workflow that builds and attests production transition manifests;
2. publish manifest, Sigstore bundle, and final ProofQA report as one immutable release unit;
3. compare candidate distributions against signed baselines;
4. aggregate multiple suites, models, and transitions into one release decision;
5. publish a dedicated immutable Marketplace action.
