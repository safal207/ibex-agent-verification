# Multi-Model Hosted Inference Evidence

The Cerebras live workflow can run the same bounded streaming request against more than one model while preserving separate, model-scoped evidence bundles.

## First comparison matrix

```text
gpt-oss-120b
zai-glm-4.7
```

The workflow checks the provider's live model catalog before sending each inference request. A configured model that is no longer returned by `models.list()` fails closed instead of producing evidence under a stale or redirected model identifier.

## Controlled variables

Both matrix entries use the same:

- provider and API endpoint;
- official pinned Cerebras SDK dependency;
- repository commit;
- user prompt: `Return a two-word greeting.`;
- chat-completions streaming mode;
- `temperature: 0`;
- `max_completion_tokens: 64`;
- request timeout of 60 seconds;
- disabled SDK retries;
- disabled TCP warming;
- evidence schema, manifest verifier, and receipt renderer.

The intended independent variable is the exact model ID.

## Evidence isolation

Each model receives a separate directory and Actions artifact:

```text
artifacts/gpt-oss-120b/
artifacts/zai-glm-4-7/
```

Every artifact contains its own:

- provider model-catalog snapshot;
- sanitized request JSON;
- raw streaming capture;
- normalized analysis;
- evidence manifest;
- independent manifest verification report;
- run report;
- JSON and Markdown receipts.

The workflow verifies that the model written into the evidence manifest exactly equals the model selected by the matrix.

## What can be compared

A successful pair of runs supports a narrow, client-observed comparison of:

- HTTP completion status;
- time to first output;
- client-observed total duration;
- output-token throughput when the provider exposes sufficient timing and usage data;
- provider-reported completion time when available;
- stream shape and usage metadata;
- SDK and endpoint identity.

## What cannot be concluded from one stream

One short request does not establish:

- overall model quality;
- coding or reasoning superiority;
- stable provider-wide latency;
- hardware architecture or utilization;
- cost efficiency across real workloads;
- statistically significant performance differences.

Those claims require a versioned prompt corpus, repeated samples, randomized run order, warm/cold separation, error-rate accounting, and statistical analysis. The two-model matrix is the first controlled evidence rail, not a leaderboard.
