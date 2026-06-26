# OpenAI-Compatible Inference Evidence

`ibex-av build-inference-evidence` is an experimental, provider-neutral adapter for a recorded OpenAI-compatible streaming inference request.

The first intended target is Cerebras Cloud, but the capture contract does not assume Cerebras hardware or a Cerebras-specific SDK. The same contract can describe another OpenAI-compatible endpoint.

## Claim boundary

This adapter verifies and preserves an API-level observation:

- the sanitized request body;
- a timestamped stream of response events;
- HTTP status;
- time to first output;
- end-to-end duration;
- provider-reported token usage;
- derived output tokens per second;
- hashes for the captured output and every bundle file.

It does **not** verify:

- Cerebras WSE hardware or internal RTL;
- the physical machine that served a request;
- energy efficiency;
- model quality or semantic correctness;
- an independently counted token total;
- a vendor-wide performance claim.

The initial throughput value uses provider-reported `completion_tokens`. If usage is absent, malformed, or internally inconsistent, the adapter does not estimate tokens per second.

## Input files

### Sanitized request JSON

The request is a normal JSON object containing fields such as `model`, `messages`, `temperature`, and `max_tokens`.

Do not place credentials in this file. Top-level `authorization`, `api_key`, and `api-key` fields are rejected. Authorization headers are outside this evidence contract.

### Capture JSONL

Each non-empty line is one JSON object with:

- `event`: event type;
- `monotonic_ns`: non-negative client monotonic timestamp in nanoseconds.

Supported event types:

- `request_start` — exactly one and always first;
- `response_headers` — optional, at most one, with `status_code`;
- `chunk` — zero or more OpenAI-compatible streaming payloads;
- `request_end` — successful terminal event;
- `request_error` — failed terminal event with a non-empty `error` string.

Exactly one terminal event must be last. Timestamps must be non-decreasing.

Example:

```jsonl
{"event":"request_start","monotonic_ns":1000000000}
{"event":"response_headers","monotonic_ns":1050000000,"status_code":200}
{"event":"chunk","monotonic_ns":1100000000,"payload":{"choices":[{"delta":{"content":"Hello"}}]}}
{"event":"chunk","monotonic_ns":1300000000,"payload":{"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":20,"total_tokens":28}}}
{"event":"request_end","monotonic_ns":1500000000}
```

A usage object must contain non-negative integer values for `prompt_tokens`, `completion_tokens`, and `total_tokens`, and the total must equal prompt plus completion tokens.

## Metrics

The adapter derives:

- `duration_ms`: terminal timestamp minus request start;
- `time_to_first_output_ms`: first non-empty content, tool call, function call, or refusal delta minus request start;
- `generation_ms`: terminal timestamp minus first output timestamp;
- `output_tokens_per_second`: provider-reported completion tokens divided by generation duration.

The throughput source is explicitly recorded as `provider_usage`, and `estimated` remains `false`.

## Usage

```bash
ibex-av build-inference-evidence \
  --provider cerebras \
  --model example-model \
  --project-sha "$(git rev-parse HEAD)" \
  --request request.json \
  --capture capture.jsonl \
  --evidence-dir artifacts/cerebras-run
```

The output directory must be empty or absent. It will contain:

```text
artifacts/cerebras-run/
├── analysis.json
├── manifest.json
└── raw/
    ├── capture.jsonl
    └── request.json
```

Verify the completed bundle independently:

```bash
ibex-av verify-evidence \
  --manifest artifacts/cerebras-run/manifest.json \
  --report artifacts/cerebras-run-verification.json
```

Keep the optional CLI and verification reports outside the evidence directory so they do not become unlisted post-manifest files.

## Exit codes

- `0`: the recorded request completed with a 2xx HTTP status;
- `1`: the capture is structurally valid but records a failed request;
- `2`: malformed, unsafe, incomplete, or unreadable input.

## Current limitation

This first slice analyzes an already-recorded event stream. It does not yet make an HTTP request or measure multiple repetitions. A future runner should capture events directly from a pinned SDK/client version, preserve safe response headers, record warmups and repetitions, and report p50/p95 without weakening this raw evidence contract.
