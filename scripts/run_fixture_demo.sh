#!/usr/bin/env bash
set -euo pipefail

mkdir -p artifacts
python -m ibex_agent_verification compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_pass.jsonl \
  --report artifacts/pass-report.json

python -m ibex_agent_verification parse-ibex-trace \
  --input tests/fixtures/ibex_tracer/official_sample_022f0840.log \
  --output artifacts/ibex-architectural.jsonl \
  --metadata-output artifacts/ibex-metadata.jsonl \
  --timing-output artifacts/ibex-timing.jsonl \
  --report artifacts/ibex-parser-report.json

set +e
python -m ibex_agent_verification compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_fail.jsonl \
  --report artifacts/fail-report.json
compare_status=$?

python -m ibex_agent_verification analyze-timing \
  --input examples/timing/memory_wait.jsonl \
  --report artifacts/timing-report.json
synthetic_timing_status=$?

python -m ibex_agent_verification analyze-timing \
  --input artifacts/ibex-timing.jsonl \
  --report artifacts/ibex-timing-report.json
ibex_timing_status=$?
set -e

if [[ "$compare_status" -ne 1 ]]; then
  echo "Expected deliberate mismatch to exit with code 1, got $compare_status" >&2
  exit 1
fi

if [[ "$synthetic_timing_status" -ne 1 ]]; then
  echo "Expected synthetic timing anomaly to exit with code 1, got $synthetic_timing_status" >&2
  exit 1
fi

if [[ "$ibex_timing_status" -ne 1 ]]; then
  echo "Expected documented Ibex sample cycle gap to exit with code 1, got $ibex_timing_status" >&2
  exit 1
fi

bash ./scripts/run_silicon_gate_demo.sh artifacts/silicon-gate-demo

echo "Fixture demo completed: functional comparison, official Ibex trace parsing, timing analysis, and silicon evidence gating."
