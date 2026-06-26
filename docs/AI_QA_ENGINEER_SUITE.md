# AI QA Engineer Verification Suite

The AI QA Engineer Verification Suite measures whether a hosted language model can complete constrained, reviewable QA tasks under a fixed request and scoring contract.

It combines the repository's hosted inference evidence rail with deterministic QA-oriented scoring. A model does not receive points for persuasive prose, verbosity, or matching another model's opinion. It receives points only for exact JSON fields evaluated by ordinary code.

## Core suite v0.1

The first version contains five tasks:

| Task | QA capability |
|---|---|
| `bug-triage-idempotency` | root-cause analysis, severity, ownership, regression selection |
| `test-design-boundaries` | boundary-value and invalid-type selection |
| `api-contract-statuses` | HTTP contract interpretation |
| `sql-result-paid-orders` | SQL filtering, grouping, aggregation, and ordering |
| `logs-duplicate-order` | ordered-log analysis and preventive-control selection |

The versioned source is:

```text
benchmarks/qa-engineer-core-v0.1.json
```

Changing a prompt, expected answer, task order, or completion budget requires changing the corpus file and therefore changes its SHA-256.

## Scoring contract

Each prompt requires one strict JSON object:

- no Markdown fences;
- no explanatory prose;
- no extra keys;
- exact JSON types;
- exact values or array ordering;
- no credential-like keys.

The scorer awards one point for exact structure and one point for each expected leaf value. This exposes partial failures. A model can identify the correct root cause while still losing a point for an incorrect severity or owner.

The scorer is deterministic. It does not ask a second language model to grade the first model.

## Live execution

The GitHub Actions workflow runs the suite independently for:

```text
gpt-oss-120b
zai-glm-4.7
```

For each model it:

1. verifies the model is present in the live Cerebras model catalog;
2. prepares five model-bound requests from the versioned corpus;
3. records each raw streaming interaction;
4. builds and independently verifies an inference evidence manifest;
5. scores the exact streamed JSON response;
6. produces a per-model summary;
7. builds an outer SHA-256 manifest covering the corpus-derived requests, captures, inference manifests, score reports, model catalog, and summary;
8. scans every output for the repository credential value;
9. uploads a model-scoped evidence artifact.

A wrong model answer is a benchmark result, not an infrastructure exception. Missing evidence, malformed manifests, unavailable models, missing credentials, or inconsistent identities fail the workflow.

## Evidence shape

```text
qa-benchmark/
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

## What the score means

The score supports a narrow claim:

> On this exact versioned set of constrained QA tasks, the model produced these exact responses and earned these deterministic field-level points.

It does not prove:

- general model intelligence;
- full QA Engineer seniority;
- exploratory testing skill;
- product judgment under ambiguity;
- production safety;
- stable latency or quality across time;
- superiority over another model on unseen work.

## Planned progression

Future independently versioned suites can add:

- mobile lifecycle and offline-sync failures;
- web state and browser compatibility;
- API schema and integration chains;
- SQL mutation and transaction isolation;
- security and prompt-injection resistance;
- log correlation and distributed tracing;
- test automation review;
- CI/CD failure diagnosis;
- product-risk prioritization;
- communication and bug-report quality.

Repeated runs, randomized order, hidden holdout tasks, statistical confidence intervals, and human review are required before treating results as a robust model comparison.
