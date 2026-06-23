#!/usr/bin/env bash
set -euo pipefail

mkdir -p artifacts
python -m ibex_agent_verification compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_pass.jsonl \
  --report artifacts/pass-report.json

set +e
python -m ibex_agent_verification compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_fail.jsonl \
  --report artifacts/fail-report.json
compare_status=$?

python -m ibex_agent_verification analyze-timing \
  --input examples/timing/memory_wait.jsonl \
  --report artifacts/timing-report.json
timing_status=$?
set -e

if [[ "$compare_status" -ne 1 ]]; then
  echo "Expected deliberate mismatch to exit with code 1, got $compare_status" >&2
  exit 1
fi

if [[ "$timing_status" -ne 1 ]]; then
  echo "Expected timing anomaly to exit with code 1, got $timing_status" >&2
  exit 1
fi

echo "Fixture demo completed: MATCH, expected MISMATCH, and timing anomaly detected."
