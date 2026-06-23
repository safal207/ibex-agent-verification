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
status=$?
set -e

if [[ "$status" -ne 1 ]]; then
  echo "Expected deliberate mismatch to exit with code 1, got $status" >&2
  exit 1
fi

echo "Fixture demo completed: one MATCH and one expected MISMATCH."
