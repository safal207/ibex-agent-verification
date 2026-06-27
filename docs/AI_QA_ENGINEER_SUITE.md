# AI QA Engineer Verification Suites

The AI QA Engineer verification rail measures whether a hosted language model can complete constrained, reviewable QA tasks under fixed request, scoring, and evidence contracts.

A model does not receive points for persuasive prose, verbosity, or matching another model's opinion. It receives points only for exact JSON fields evaluated by ordinary deterministic code.

## Versioned suites

The catalog currently contains two suites:

| Suite | Focus | Tasks |
|---|---|---:|
| `qa-engineer-core-v0.1` | bug triage, test design, API contracts, SQL, and logs | 5 |
| `mobile-qa-engineer-v0.1` | lifecycle, offline sync, permissions, deep links, and migration | 5 |

Sources:

```text
benchmarks/qa-engineer-core-v0.1.json
benchmarks/mobile-qa-engineer-v0.1.json
```

Changing a prompt, expected answer, task order, or completion budget changes the corpus file and therefore its SHA-256.

The workflow inventory is defined by:

```text
benchmarks/qa-suite-catalog.json
```

The catalog is validated before live inference. Suite paths must remain inside the repository, IDs and task counts must match the actual files, and model/suite slugs must be unique.

## Task scoring contract

Each prompt requires one strict JSON object:

- no Markdown fences;
- no explanatory prose;
- no extra keys;
- exact JSON types;
- exact values and array ordering;
- no credential-like keys.

The task scorer awards one point for exact structure and one point for each expected leaf value. Invalid, failed, and output-truncated responses retain the full task denominator, so every model is compared against the same possible score.

`finish_reason=length` is reported explicitly as `OUTPUT_TRUNCATED`, rather than being disguised as an ordinary wrong answer.

The scorer is deterministic. It does not ask a second language model to grade the first model.

## Scorecard v3

A single percentage cannot distinguish knowledge errors, answer-completion failures, provider outages, and slow delivery. Every suite/model summary therefore publishes four orthogonal diagnostic axes plus the strict end-to-end score.

### End-to-end score

Field-level points across every configured task. Invalid JSON, truncation, and provider failure receive zero points while retaining the task's full denominator.

### Answer correctness

Field-level points only across tasks that produced valid strict JSON and were scored `PASS` or `FAIL`.

When no task produced a valid strict-JSON answer, the percentage is `null` and displayed as `n/a`, not zero.

### Completion reliability

```text
completed PASS-or-FAIL tasks / all configured tasks
```

`INVALID_RESPONSE`, `OUTPUT_TRUNCATED`, and `INFERENCE_FAILED` are incomplete.

### Provider reliability

```text
successful HTTP 2xx requests / known provider outcomes
```

A request returning HTTP 2xx remains a provider success even when the model emits invalid JSON or reaches `finish_reason=length`. HTTP 429, other non-2xx responses, timeouts, and transport failures reduce provider reliability.

### Time performance

Scorecard v3 preserves client-observed monotonic timing for each task:

- total request duration;
- time to first output;
- generation time after first output.

For each metric it records deterministic `minimum`, `p50`, `p95`, and `maximum` distributions. Percentiles use linear interpolation over the ordered samples.

The successful-request duration distribution includes only known provider successes. A fast HTTP 429 is excluded from the time axis and remains a provider failure. A truncated HTTP-2xx response may be fast while still reducing completion reliability.

The scorecard records timing facts but does not declare one universal latency target. ProofQA Release Gate applies a product-specific `max-p95-duration-ms` policy.

### Reading all axes together

```text
End-to-end score:          10/25 = 40%
Answer correctness:        10/10 = 100%
Completion reliability:     2/5  = 40%
Provider reliability:        5/5  = 100%
Successful p95 duration:   900 ms
```

This means the completed answers were fully correct, all requests were served successfully, and successful requests completed within the observed latency distribution—but three tasks never produced valid final JSON.

The scorecard also records separate outcome counts for `PASS`, `FAIL`, `INVALID_RESPONSE`, `OUTPUT_TRUNCATED`, and `INFERENCE_FAILED`, plus provider failure classes such as `http_429` or `transport_timeout_or_unknown`.

## Live execution

The GitHub Actions workflow builds a validated cross-product of every configured suite and model. The current models are:

```text
gpt-oss-120b
zai-glm-4.7
```

Jobs run sequentially, with a cooldown before each inference, to reduce provider quota noise. Cooldown and workflow setup time are outside the capture and therefore outside the time axis.

For each suite/model pair the workflow:

1. verifies the model is present in the live Cerebras model catalog;
2. validates the selected suite identity and task count;
3. prepares model-bound requests from the versioned corpus;
4. records each raw streaming interaction with monotonic timestamps;
5. builds and independently verifies an inference evidence manifest;
6. scores the exact streamed JSON response;
7. produces scorecard v3 with correctness, completion, provider, and time diagnostics;
8. builds an outer SHA-256 manifest covering requests, captures, inference manifests, score reports, model catalog, and summary;
9. scans every output for the repository credential value;
10. uploads a suite-and-model-scoped evidence artifact.

A wrong model answer is a benchmark result, not an infrastructure exception. Missing evidence, malformed manifests, unavailable models, missing credentials, inconsistent identities, or an invalid catalog fail the workflow.

## Evidence shape

```text
artifacts/<suite-slug>/<model-slug>/
├── qa-benchmark-verification.json
└── qa-benchmark/
    ├── manifest.json
    ├── model-catalog.json
    ├── summary.json
    └── tasks/
        └── <task-id>/
            ├── request.json
            ├── run-report.json
            ├── score.json
            ├── verification.json
            └── evidence/
                ├── analysis.json
                ├── manifest.json
                └── raw/
                    ├── capture.jsonl
                    └── request.json
```

The outer verification report is stored next to the bundle so it cannot silently modify the bundle it verifies.

## What a scorecard means

A scorecard supports a narrow claim:

> On this exact versioned task set, the model produced these exact responses, completed this fraction of tasks, experienced these provider outcomes, and had these client-observed timing distributions.

It does not prove:

- general model intelligence;
- complete QA Engineer seniority;
- exploratory testing skill;
- production safety;
- stable latency or quality across time;
- superiority on unseen work.

One five-task run is not a stable latency benchmark. Repeated samples, environment controls, sample-size disclosure, randomized order, and confidence intervals are required for durable performance claims.

## Planned progression

Future independently versioned suites can add web, API, SQL, security, distributed tracing, automation review, CI/CD diagnosis, product-risk prioritization, and communication quality.

Future timing work can add signed baselines, repeated-run distributions, confidence intervals, and a careful separation of provider queue time from model execution when trustworthy provider timing is available.
