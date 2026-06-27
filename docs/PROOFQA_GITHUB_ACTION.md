# ProofQA Release Gate GitHub Action

ProofQA converts a deterministic QA scorecard v2 or v3 summary into a CI decision:

```text
PASS
WARN
BLOCK
```

The gate keeps five concerns separate instead of treating one blended number as model quality:

- end-to-end score;
- answer correctness on completed strict-JSON tasks;
- completion reliability;
- provider reliability;
- client-observed time performance.

Scorecard v3 measures time. The release policy decides whether the measured p95 satisfies a product SLO.

## Usage

The repository has a separate root silicon action, so ProofQA is exposed from the `proofqa` subdirectory:

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
    max-p95-duration-ms: "2000"
    time-warn-margin-ms: "250"
    unknown-metric-policy: block
    fail-on: block
    report-path: artifacts/proofqa-gate-report.json
```

Pin the action to a full commit SHA. A future dedicated `proofqa-action` repository can publish immutable releases without replacing the existing root silicon action.

## Time-axis semantics

Scorecard v3 derives time from the monotonic timestamps inside each preserved inference capture. It does not use total GitHub job duration, SDK installation time, configured cooldown, or unrelated workflow queue time.

It records deterministic distributions for:

- total client-observed request duration;
- time to first output;
- generation time after first output.

Each distribution contains:

```text
count
minimum
p50
p95
maximum
```

Percentiles use linear interpolation over the ordered observed values.

The release gate applies `max-p95-duration-ms` to the total duration of successful HTTP-2xx requests. Provider failures are excluded from the latency distribution and remain visible on the provider-reliability axis. A fast HTTP 429 therefore does not improve the time result. A truncated HTTP-2xx request may satisfy the time SLO while still failing completion reliability.

This separation lets a report say all of the following without contradiction:

```text
Answer correctness:      100% PASS
Completion reliability:   40% BLOCK
Provider reliability:    100% PASS
Successful p95 duration:  900 ms PASS
```

The model returned correct answers when it completed, the provider served every request, and the observed requests were fast enough—but most tasks still failed to produce usable final JSON.

## Time decisions

For an enabled time policy:

1. p95 above `max-p95-duration-ms` produces `BLOCK`;
2. p95 at or below the maximum but above `maximum - time-warn-margin-ms` produces `WARN`;
3. p95 below the warning band produces `PASS`;
4. missing p95 follows `unknown-metric-policy`.

Set:

```yaml
max-p95-duration-ms: "0"
```

to disable the time gate. This preserves compatibility with scorecard v2 summaries, which do not contain timing distributions.

## Adoption modes

### Observe without blocking

```yaml
- uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
  id: proofqa
  with:
    summary-path: artifacts/qa-benchmark/summary.json
    max-p95-duration-ms: "2000"
    fail-on: never
```

The action still emits a decision, writes the report, adds the Actions summary, and exposes outputs. It does not fail the workflow.

### Block failed policy only

```yaml
with:
  fail-on: block
```

`WARN` remains visible. `BLOCK` exits non-zero.

### Treat warning as failure

```yaml
with:
  fail-on: warn
```

Both `WARN` and `BLOCK` fail the action.

## Inputs

| Input | Default | Meaning |
|---|---:|---|
| `summary-path` | required | ProofQA `summary.json` with scorecard v2 or v3 |
| `policy-name` | `default` | name stored in report and Actions summary |
| `min-end-to-end` | `90` | minimum strict full-denominator score |
| `min-answer-correctness` | `90` | minimum correctness on completed answers |
| `min-completion-reliability` | `95` | minimum percentage producing valid JSON |
| `min-provider-reliability` | `95` | minimum successful known provider outcomes |
| `warn-margin` | `3` | warning band above percentage minimums |
| `max-p95-duration-ms` | `0` | maximum successful-request p95; zero disables time gate |
| `time-warn-margin-ms` | `250` | warning band below the p95 maximum |
| `unknown-metric-policy` | `block` | `block`, `warn`, or `ignore` for null metrics |
| `fail-on` | `block` | `block`, `warn`, or `never` |
| `report-path` | `proofqa-gate-report.json` | machine-readable report destination |

Percentage inputs must be finite values from `0` through `100`. Time inputs must be finite non-negative millisecond values up to one hour.

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
| `p95-duration-ms` | `900.000000` or `n/a` |

## Gate report

The generated JSON binds:

- percentage and time thresholds;
- final decision and enforcement result;
- all observed metrics;
- one finding per axis;
- suite, provider, model, and scorecard identity;
- source summary path and SHA-256;
- the claim boundary.

The report can be uploaded as a workflow artifact or included in a larger release evidence manifest.

## Fail-closed behavior

The action returns configuration error exit code `2` when:

- `summary-path` is missing;
- the summary is not a regular non-symlink file;
- JSON is malformed;
- scorecard version/schema pairing is invalid;
- a metric is not finite or falls outside its permitted range;
- a policy value is invalid;
- the report would overwrite the source summary.

A malformed evidence contract cannot become a permissive `PASS`.

## Security and claim boundary

The action:

- requests no repository write permissions;
- requires no `GITHUB_TOKEN` or provider credential;
- uses a pinned Python setup action;
- reads one already-produced scorecard;
- writes one machine-readable report;
- publishes scorecard metadata and thresholds to the Actions summary.

It does not rerun the model, verify the outer evidence manifest, or prove stable latency from one five-task sample. Stable latency claims require repeated runs, controlled environments, sample-size disclosure, and trend analysis.

## Next increments

1. compare candidate time distributions against a signed baseline;
2. aggregate repeated runs and confidence intervals;
3. separate provider queue time from model execution when trustworthy provider timing exists;
4. aggregate multiple suites and models into one release decision;
5. publish a dedicated immutable action repository and Marketplace release.
