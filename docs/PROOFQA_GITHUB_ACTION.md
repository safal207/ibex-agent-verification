# ProofQA Release Gate GitHub Action

ProofQA converts a deterministic QA scorecard v2 or v3 and, optionally, one Transition Phase Contract report into a CI decision:

```text
PASS
WARN
BLOCK
```

The gate keeps six concerns separate instead of blending them into one model-quality number:

- end-to-end score;
- answer correctness on completed strict-JSON tasks;
- completion reliability;
- provider reliability;
- client-observed time performance;
- transition readiness across time, intention, and space.

Scorecard v3 measures time. The transition report answers a different question: whether the claimed movement from one state or context to another is complete and safe to continue.

## Usage

The repository has a separate root silicon action, so ProofQA is exposed from the `proofqa` subdirectory:

```yaml
- name: Evaluate AI QA release evidence
  id: proofqa
  uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
  with:
    summary-path: artifacts/mobile-v0-1/gpt-oss-120b/qa-benchmark/summary.json
    transition-report-path: artifacts/release-transition-report.json
    transition-policy: require-verified
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

## Transition policy

`transition-policy` has three modes:

| Mode | Transition report | Effect |
|---|---|---|
| `ignore` | not required | transition finding is disabled; preserves old pipelines |
| `warn` | required | `VERIFIED` passes; `IN_PROGRESS` or `RECALIBRATE` produces `WARN` |
| `require-verified` | required | only `VERIFIED` passes; other states produce `BLOCK` |

A `VERIFIED` label is not accepted by itself. The action also requires:

```text
phase: REFLECT
next_phase: CONTINUE
issues: []
time.status: PASS
intention.status: PASS
space.status: PASS
```

This prevents a report from hiding an unfinished or contradictory transition behind a single optimistic status field.

For `IN_PROGRESS`, only `CALIBRATE`, `EXPAND`, `COMMIT`, `EXECUTE`, or `VERIFY` are allowed and no axis may be `BLOCK`.

For `RECALIBRATE`, the report must use:

```text
phase: RECALIBRATE
next_phase: CALIBRATE
```

and contain at least one issue or one blocked axis.

### Gradual adoption

Start by surfacing unfinished transitions without blocking production:

```yaml
with:
  transition-report-path: artifacts/release-transition-report.json
  transition-policy: warn
  fail-on: block
```

The overall decision becomes `WARN`, but block-only enforcement keeps the workflow green.

Move to strict continuation control when report generation is stable:

```yaml
with:
  transition-report-path: artifacts/release-transition-report.json
  transition-policy: require-verified
  fail-on: block
```

Now `IN_PROGRESS` and `RECALIBRATE` fail the action even when every scorecard and time axis passes.

## Time-axis semantics

Scorecard v3 derives time from monotonic timestamps inside each preserved inference capture. It does not use total GitHub job duration, SDK installation time, configured cooldown, or unrelated workflow queue time.

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

Percentiles use linear interpolation over ordered observed values.

The release gate applies `max-p95-duration-ms` to successful HTTP-2xx request duration. Provider failures are excluded from latency and remain visible on the provider-reliability axis. A fast HTTP 429 therefore does not improve the time result. A truncated HTTP-2xx request may satisfy the time SLO while still failing completion reliability.

This separation allows a report such as:

```text
Answer correctness:      100% PASS
Completion reliability:  100% PASS
Provider reliability:    100% PASS
Successful p95 duration:  900 ms PASS
Transition phase:        RECALIBRATE BLOCK
```

The model and provider passed, but the declared release transition is not safe to continue.

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

## Workflow enforcement

### Observe without failing

```yaml
with:
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
| `transition-report-path` | empty | Transition Phase Contract verification report |
| `transition-policy` | `ignore` | `ignore`, `warn`, or `require-verified` |
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
| `transition-status` | `VERIFIED`, `IN_PROGRESS`, `RECALIBRATE`, or `n/a` |
| `transition-phase` | `REFLECT`, `EXPAND`, `RECALIBRATE`, or `n/a` |
| `transition-sha256` | 64-character SHA-256 or `n/a` |

## Gate report v3

The generated JSON binds:

- percentage, time, and transition policies;
- final decision and enforcement result;
- all observed scorecard metrics;
- one finding per independent axis;
- suite, provider, model, and scorecard identity;
- source summary path and SHA-256;
- transition report path, identity, phase, status, and SHA-256 when enabled;
- the claim boundary.

The transition axis is never blended into the numeric score. A strict transition failure can therefore block continuation without pretending that model correctness changed.

The report can be uploaded as a workflow artifact or included in a larger release evidence manifest.

## Fail-closed behavior

The action returns configuration error exit code `2` when:

- `summary-path` is missing;
- a non-ignored transition policy lacks `transition-report-path`;
- a source is not a regular non-symlink file;
- JSON is malformed;
- scorecard version/schema pairing is invalid;
- transition status, phase, next phase, issues, or axes are inconsistent;
- a metric is not finite or falls outside its permitted range;
- a policy value is invalid;
- the generated report would overwrite either source report.

A malformed evidence contract cannot become a permissive `PASS`.

## Security and claim boundary

The action:

- requests no repository write permissions;
- requires no `GITHUB_TOKEN` or provider credential;
- uses a pinned Python setup action;
- reads one scorecard and optionally one transition report;
- hashes both consumed reports;
- writes one machine-readable gate report;
- publishes policy and evidence identities to the Actions summary.

The action validates the internal Transition Phase Contract and binds the report bytes by SHA-256. It does not independently verify the external evidence references inside that transition report. Stronger continuation claims should include the transition report and its referenced evidence in a verified manifest or signed release bundle.

It also does not rerun the model or prove stable latency from one small sample. Stable latency and quality claims require repeated runs, controlled environments, sample-size disclosure, and trend analysis.

## Next increments

1. require the transition report and referenced evidence inside one verified manifest;
2. compare candidate time distributions against a signed baseline;
3. aggregate repeated runs and confidence intervals;
4. aggregate multiple suites, models, and transitions into one release decision;
5. publish a dedicated immutable action repository and Marketplace release.
