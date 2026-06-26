# Hosted Cerebras Evidence — 2026-06-26

This page records the first fully green hosted inference evidence run produced by `ibex-agent-verification`.

## Run identity

- GitHub Actions run: [28255376630](https://github.com/safal207/ibex-agent-verification/actions/runs/28255376630)
- Job: `83716980407`
- Project commit: `9af7b7de6867d83321c935e37aeef9bf2b312bc1`
- Provider adapter: `cerebras`
- Model: `gpt-oss-120b`
- SDK: `cerebras_cloud_sdk==1.67.0`
- Endpoint: `https://api.cerebras.ai`
- Retries: disabled
- TCP warming: disabled

## Verified result

| Field | Value |
|---|---:|
| Evidence status | `COMPLETE` |
| HTTP status | `200` |
| Bundle verification | `VERIFIED` |
| Manifest files checked | `3` |
| Mismatches | `0` |
| Client duration | `204.233532 ms` |
| Time to first visible output | `203.354406 ms` |
| Provider completion time | `0.032944668 s` |
| Completion tokens | `63` |
| Reasoning tokens | `51` |
| Output throughput | `1912.297310144391 tokens/s` |
| Throughput source | `provider_usage_and_time_info` |

The throughput is computed from provider-reported completion tokens divided by provider-reported completion time. It is not computed from the much shorter interval after the first visible text, because the response included reasoning tokens before visible output.

## Durable evidence

The exact sanitized bundle is committed under:

```text
docs/evidence/releases/v0.8.0/cerebras-live/
```

The bundle manifest inventories `analysis.json`, `raw/capture.jsonl`, and `raw/request.json`. The adjacent `verification.json` records `VERIFIED` with zero mismatches. Release `v0.8.0` packages the same committed files into a deterministic ZIP asset so the record does not depend on the 14-day retention period of the original Actions artifact.

Verify the committed bundle locally:

```bash
ibex-av verify-evidence \
  --manifest docs/evidence/releases/v0.8.0/cerebras-live/bundle/manifest.json \
  --report /tmp/cerebras-live-verification.json
```

## Claim boundary

This evidence proves that one client-observed OpenAI-compatible streaming request completed successfully, that the preserved request/capture/analysis files match their manifest, and that the reported throughput uses provider usage and provider completion timing.

It does **not** verify Cerebras internal hardware identity, WSE or RTL correctness, energy efficiency, model quality, service-wide availability, or a vendor-wide tokens-per-second benchmark. The repository is independent and is not endorsed by Cerebras.
