# Verification Protocol

A result can be labeled `MISMATCH` only when all required evidence is present.

## Required manifest fields

- repository version
- Ibex upstream revision
- Ibex configuration
- compiler identity and version
- simulator identity and version
- program source and binary SHA-256
- random seed, if any
- exact commands
- raw DUT output
- raw oracle output
- normalized traces
- comparator report

## Bundle verification

After downloading an evidence directory, verify it before reading its reports:

```bash
ibex-av verify-evidence --manifest artifacts/ibex-e2e/manifest.json
```

The command checks manifest paths, file sizes, SHA-256 values, and the complete file inventory. See [Evidence Bundle Verification](EVIDENCE_BUNDLE_VERIFICATION.md).

## Experimental inference evidence

A recorded OpenAI-compatible inference run may be packaged with:

```bash
ibex-av build-inference-evidence \
  --provider cerebras \
  --model example-model \
  --project-sha "$(git rev-parse HEAD)" \
  --request request.json \
  --capture capture.jsonl \
  --evidence-dir artifacts/cerebras-run
```

This is an API-observation contract, not a silicon verification result. It preserves client monotonic timestamps, raw response chunks, provider-reported usage, derived latency, and file hashes. Missing usage produces no tokens-per-second estimate. See [OpenAI-Compatible Inference Evidence](INFERENCE_EVIDENCE.md).

## Result states

- `MATCH`: all normalized events match.
- `MISMATCH`: at least one deterministic semantic difference exists.
- `COMPLETE`: a structurally valid recorded inference request completed with a 2xx HTTP status.
- `REQUEST_FAILED`: a structurally valid inference capture records an HTTP or client failure.
- `INVALID_INPUT`: trace, capture, or manifest is malformed.
- `BLOCKED`: an external dependency or tool failed.
- `INCONCLUSIVE`: evidence exists but the comparison contract does not cover the observed behavior.

## Reporting rule

`MISMATCH` is not automatically an Ibex defect. The discrepancy may be caused by the test, compiler, parser, oracle, unsupported behavior, or environment. A human must classify root cause before an upstream issue is opened.

An inference `COMPLETE` result is not evidence that a provider's accelerator hardware is correct or that a published benchmark is independently reproduced. It only confirms the recorded API interaction and deterministic metrics derived from that capture.
