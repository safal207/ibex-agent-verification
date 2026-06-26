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

## Scoring contract

Each prompt requires one strict JSON object:

- no Markdown fences;
- no explanatory prose;
- no extra keys;
- exact JSON types;
- exact values and array ordering;
- no credential-like keys.

The scorer awards one point for exact structure and one point for each expected leaf value. Invalid, failed, and output-truncated responses retain the full task denominator, so every model is compared against the same possible score.

`finish_reason=length` is reported explicitly as `OUTPUT_TRUNCATED`, rather than being disguised as an ordinary wrong answer.

The scorer is deterministic. It does not ask a second language model to grade the first model.

## Live execution

The GitHub Actions workflow builds a validated cross-product of every configured suite and model. The current models are:

```text
gpt-oss-120b
zai-glm-4.7
```

Jobs run sequentially, with a cooldown before each inference, to reduce provider quota noise. For each suite/model pair the workflow:

1. verifies the model is present in the live Cerebras model catalog;
2. validates the selected suite identity and task count;
3. prepares model-bound requests from the versioned corpus;
4. records each raw streaming interaction;
5. builds and independently verifies an inference evidence manifest;
6. scores the exact streamed JSON response;
7. produces a suite/model summary;
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

## What a score means

A score supports a narrow claim:

> On this exact versioned set of constrained QA tasks, the model produced these exact responses and earned these deterministic field-level points.

It does not prove:

- general model intelligence;
- complete QA Engineer seniority;
- exploratory testing skill;
- product judgment under ambiguity;
- production safety;
- stable latency or quality across time;
- superiority on unseen work.

## Planned progression

Future independently versioned suites can add:

- web state and browser compatibility;
- API schema and multi-service integration chains;
- SQL mutation and transaction isolation;
- security and prompt-injection resistance;
- distributed tracing and log correlation;
- test automation review;
- CI/CD failure diagnosis;
- product-risk prioritization;
- communication and bug-report quality.

Repeated runs, randomized order, hidden holdout tasks, statistical confidence intervals, device-lab execution, and human review are required before treating results as a robust model comparison.
