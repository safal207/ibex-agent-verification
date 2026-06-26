# Mobile QA Engineer Verification Suite v0.1

The mobile suite evaluates exact safety decisions in five constrained application incidents. It uses the same deterministic scorer and evidence contract as the core AI QA Engineer suite.

## Covered incidents

| Task | Mobile risk |
|---|---|
| `lifecycle-payment-recovery` | process death after server commit but before client acknowledgement |
| `offline-sync-version-conflict` | optimistic-concurrency conflict after offline editing |
| `android-permission-permanent-denial` | Android permission denied with "Don't ask again" |
| `authenticated-push-deep-link` | trusted notification deep link through expired authentication |
| `transactional-database-migration` | crash during an uncommitted local database migration |

The versioned source is:

```text
benchmarks/mobile-qa-engineer-v0.1.json
```

## What is scored

The tasks check whether the model selects behavior that protects the user and system state:

- reconcile a committed payment without submitting it twice;
- preserve an offline draft instead of silently overwriting newer server data;
- stop looping a permanently denied permission request while preserving a fallback;
- retain a trusted deep-link destination through authentication and consume it once;
- rely on transactional rollback and preserve local rows after migration failure.

Every answer must be one strict JSON object using only the enumerated values in the prompt. One point is awarded for exact structure and one point for each expected leaf value.

## What this suite does not prove

The suite does not measure:

- rendering correctness across real devices;
- accessibility or localization quality;
- battery, thermal, memory, or radio performance;
- OEM-specific Android behavior;
- complete iOS or Android platform knowledge;
- exploratory testing skill;
- production readiness.

Those require device labs, platform-specific automation, repeated runs, hidden cases, and human review.

## Catalog-driven execution

The workflow matrix is generated from:

```text
benchmarks/qa-suite-catalog.json
```

The catalog validator confirms that:

- every suite path stays inside the repository;
- every file is a regular non-symlink file;
- the catalog `suite_id` matches the suite file;
- the declared task count matches the actual task count;
- model and suite slugs are unique;
- every configured suite is crossed with every configured model.

Evidence artifacts are isolated by both suite and model:

```text
artifacts/<suite-slug>/<model-slug>/
```

Adding another versioned suite requires a corpus file and one catalog entry rather than a copied GitHub Actions job.

## Live verification records

Ordinary feature pull requests do not receive the provider credential and skip live inference. A same-repository branch whose name starts with:

```text
verify/qa-suite-live-
```

creates an explicit reviewable live run. A verification record is identified by the workflow run ID, exact head SHA, suite/model artifact names, artifact digests, score summaries, and outer-manifest verification results.

Artifacts are retained for 14 days by the workflow. One run is evidence for that exact corpus, model endpoint, request configuration, and moment in time; it is not evidence of stable quality across repeated runs.
