# ProofQA Release Gate GitHub Action

ProofQA converts a deterministic QA scorecard v2 summary into a CI decision:

```text
PASS
WARN
BLOCK
```

The gate evaluates four separate axes instead of treating one blended percentage as model quality:

- end-to-end score;
- answer correctness on completed strict-JSON tasks;
- completion reliability;
- provider reliability.

## MVP usage

The repository already has a separate root silicon action, so the ProofQA MVP is exposed from the `proofqa` subdirectory:

```yaml
- name: Evaluate AI QA release evidence
  id: proofqa
  uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
  with:
    summary-path: artifacts/mobile-v0-1/gpt-oss-120b/qa-benchmark/summary.json
    policy-name: mobile-production
    min-end-to-end: "90"
    min-answer-correctness: "95"
    min-completion-reliability: "95"
    min-provider-reliability: "99"
    warn-margin: "3"
    unknown-metric-policy: block
    fail-on: block
    report-path: artifacts/proofqa-gate-report.json
```

Pin the action to a full commit SHA. A future dedicated `proofqa-action` repository can publish immutable `v1` releases and a GitHub Marketplace listing without replacing the existing root silicon action.

## Adoption modes

### Observe without blocking

Use this during the first integrations while thresholds are being calibrated:

```yaml
- uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
  id: proofqa
  with:
    summary-path: artifacts/qa-benchmark/summary.json
    fail-on: never
```

The action still emits `PASS`, `WARN`, or `BLOCK`, writes the report, adds the Actions summary, and exposes outputs. It does not fail the workflow.

### Block failed policy only

```yaml
with:
  fail-on: block
```

`WARN` remains visible but does not fail the step. `BLOCK` exits non-zero.

### Treat warning as failure

```yaml
with:
  fail-on: warn
```

Both `WARN` and `BLOCK` fail the step. This is suitable for strict release branches after the policy has been calibrated.

## Decision rules

For every axis:

1. a value below its minimum produces `BLOCK`;
2. a value at or above the minimum but below `minimum + warn-margin` produces `WARN`;
3. a value above the warning band produces `PASS`;
4. a `null` value follows `unknown-metric-policy`:
   - `block`;
   - `warn`;
   - `ignore`.

The final decision is the most severe axis decision. The `fail-on` input controls workflow enforcement but does not change the recorded decision.

Example:

```text
End-to-end:             65.5%  → BLOCK
Answer correctness:   100.0%  → PASS
Completion reliability: 60.0% → BLOCK
Provider reliability:   80.0% → BLOCK

Final decision: BLOCK
```

This keeps model knowledge, answer completion, and provider operation visible as separate causes.

## Inputs

| Input | Default | Meaning |
|---|---:|---|
| `summary-path` | required | ProofQA `summary.json` with `scorecard_version: 2` |
| `policy-name` | `default` | name stored in the report and Actions summary |
| `min-end-to-end` | `90` | minimum strict full-denominator score |
| `min-answer-correctness` | `90` | minimum correctness on completed answers |
| `min-completion-reliability` | `95` | minimum percentage of tasks producing valid JSON |
| `min-provider-reliability` | `95` | minimum successful known provider outcomes |
| `warn-margin` | `3` | warning band in percentage points above each minimum |
| `unknown-metric-policy` | `block` | `block`, `warn`, or `ignore` for `null` metrics |
| `fail-on` | `block` | `block`, `warn`, or `never` |
| `report-path` | `proofqa-gate-report.json` | destination for the machine-readable report |

All percentage inputs must be finite values from `0` through `100`.

## Outputs

| Output | Example |
|---|---|
| `decision` | `PASS`, `WARN`, or `BLOCK` |
| `should-fail` | `true` or `false` |
| `report-path` | `artifacts/proofqa-gate-report.json` |
| `summary-sha256` | 64-character SHA-256 |
| `end-to-end-percent` | `96.551724` or `n/a` |
| `answer-correctness-percent` | `100.000000` or `n/a` |
| `completion-reliability-percent` | `60.000000` or `n/a` |
| `provider-reliability-percent` | `80.000000` or `n/a` |

A later workflow step can use the outputs:

```yaml
- name: Require an exact PASS before deployment
  if: steps.proofqa.outputs.decision != 'PASS'
  run: exit 1
```

## Gate report

The generated JSON binds:

- the policy thresholds;
- the final decision and enforcement result;
- all four observed metrics;
- one finding per axis;
- suite, provider, and model identity;
- the source summary path and SHA-256;
- the claim boundary.

The report is suitable for upload as a workflow artifact or inclusion in a larger release evidence manifest.

## Fail-closed behavior

The action returns configuration error exit code `2` when:

- `summary-path` is missing;
- the summary is not a regular non-symlink file;
- the JSON is malformed;
- `scorecard_version` is not exactly `2`;
- a metric has an invalid type or falls outside `0..100`;
- a policy value is invalid;
- the output report would overwrite the source summary.

A malformed evidence contract cannot be converted into a permissive `PASS`.

## Security boundary

The action:

- requests no repository write permissions;
- does not require `GITHUB_TOKEN` or provider credentials;
- uses a pinned `actions/setup-python` commit;
- reads one already-produced scorecard;
- writes one machine-readable gate report;
- publishes only scorecard metadata and thresholds to the Actions summary.

It does not independently rerun the underlying model, verify an outer evidence manifest, or prove stable model quality across time. Those checks belong earlier in the evidence pipeline.

## Next product increments

1. compare a candidate scorecard against a signed baseline;
2. aggregate multiple suites and models into one release decision;
3. emit GitHub Checks annotations on the exact regressed tasks;
4. support policy files committed to the consumer repository;
5. publish a dedicated immutable action repository and Marketplace release.
