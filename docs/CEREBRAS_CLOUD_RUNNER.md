# Direct Cerebras Cloud Evidence Runner

`ibex-av run-cerebras-inference` performs one authenticated streaming chat-completion request against the official Cerebras Cloud endpoint and immediately packages the observed stream as a verifiable evidence bundle.

## Claim boundary

The command verifies a client-side API observation. It does not verify Cerebras WSE RTL, physical hardware identity, energy efficiency, model quality, or a vendor-wide benchmark claim.

A successful bundle proves that the preserved request, timestamped response stream, derived metrics, and manifest-listed files are mutually consistent.

## Install the optional official SDK

```bash
python -m pip install -e '.[cerebras]'
```

The optional dependency is pinned so the client implementation used by the runner is explicit and reviewable.

## Configure credentials

Create an API key in Cerebras Cloud and expose it only through the environment:

```bash
export CEREBRAS_API_KEY='replace-with-your-key'
```

The runner has no command-line API-key option. The value is never written to the request, capture, report, or manifest.

## Prepare a streaming request

```json
{
  "model": "your-model-id",
  "stream": true,
  "stream_options": {
    "include_usage": true
  },
  "messages": [
    {
      "role": "user",
      "content": "Explain why reproducible inference evidence matters."
    }
  ],
  "temperature": 0
}
```

The request must be a regular non-symlink JSON file. Its `model` must exactly match the CLI `--model` argument, and `stream` must be `true`.

Credential-like fields are rejected recursively before any network request is attempted.

## Run one observed request

```bash
ibex-av run-cerebras-inference \
  --request request.json \
  --model your-model-id \
  --project-sha "$(git rev-parse HEAD)" \
  --timeout-seconds 60 \
  --evidence-dir artifacts/cerebras-live-run \
  --report artifacts/cerebras-live-run-report.json
```

The evidence directory must be empty or absent. The optional CLI report must be outside that directory.

## Deliberately fixed client behavior

For a reviewable first measurement, the runner fixes these settings:

- endpoint: `https://api.cerebras.ai`;
- official SDK package: `cerebras_cloud_sdk`;
- automatic retries: disabled;
- automatic TCP warming: disabled;
- clock: `time.monotonic_ns`;
- credential source: `CEREBRAS_API_KEY` environment variable.

A `CEREBRAS_BASE_URL` environment override is ignored. This prevents an inherited environment variable from redirecting the credential to another endpoint.

## Captured evidence

The raw JSONL capture contains:

- `request_start` with SDK version and fixed client settings;
- `response_headers` with status, URL, HTTP version, retry count, and an allowlist of non-sensitive headers;
- every serialized SSE chunk with a monotonic timestamp;
- `request_end`, or `request_error` when the API or network fails.

Only these response headers are eligible for persistence:

- `content-type`;
- `date`;
- `x-request-id`;
- `request-id`;
- `cf-ray`.

The bundle then contains:

```text
artifacts/cerebras-live-run/
├── analysis.json
├── manifest.json
└── raw/
    ├── capture.jsonl
    └── request.json
```

The manifest additionally records runner provenance, including SDK version, endpoint, timeout, retry policy, warming policy, clock source, and whether an environment base-URL override was ignored.

Verify it independently:

```bash
ibex-av verify-evidence \
  --manifest artifacts/cerebras-live-run/manifest.json \
  --report artifacts/cerebras-live-run-verification.json
```

## Exit codes

- `0`: the request completed with a 2xx response and produced a valid bundle;
- `1`: a real HTTP, streaming, or network failure was captured and packaged as `REQUEST_FAILED`;
- `2`: malformed or unsafe input, invalid timeout, or an incompatible response object;
- `4`: `BLOCKED` because the API key or optional official SDK is unavailable.

`BLOCKED` never produces a synthetic passing bundle.

## Current verification status

Unit and integration-style tests use a deterministic SDK test double. They verify request binding, fixed endpoint and client settings, raw stream preservation, error capture, secret redaction, client closure, bundle integrity, and CLI exit codes.

A hosted request against Cerebras Cloud remains pending until a repository or local environment provides a valid `CEREBRAS_API_KEY`. No real throughput number is claimed before that run exists.
