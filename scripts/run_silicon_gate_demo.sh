#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT_DIR}/artifacts/silicon-gate-demo}"

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

python - "${OUT_DIR}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def timing_report(*causes: str) -> dict[str, object]:
    findings = [
        {
            "step": index,
            "status": "DELAY_ANOMALY",
            "primary_cause": cause,
        }
        for index, cause in enumerate(causes, start=1)
    ]
    return {
        "status": "ANOMALY_DETECTED" if findings else "ON_TIME",
        "samples": max(1, len(findings)),
        "anomalies": len(findings),
        "findings": findings,
    }


def build_scenario(
    name: str,
    *,
    candidate_commit: str,
    candidate_causes: tuple[str, ...],
) -> None:
    scenario = root / name
    evidence = scenario / "evidence"

    write(
        evidence / "trace-comparison.json",
        {
            "status": "MATCH",
            "expected_events": 1204,
            "actual_events": 1204,
            "first_mismatch_index": None,
            "differences": {},
        },
    )
    write(evidence / "baseline-timing.json", timing_report())
    write(evidence / "candidate-timing.json", timing_report(*candidate_causes))
    write(
        evidence / "baseline-control-flow.json",
        {
            "status": "REDIRECTS_FOUND",
            "redirects": 42,
            "delayed_redirects": 0,
            "pipeline_flush_claims": 0,
        },
    )
    write(
        evidence / "candidate-control-flow.json",
        {
            "status": "REDIRECTS_FOUND",
            "redirects": 42,
            "delayed_redirects": 0,
            "pipeline_flush_claims": 0,
        },
    )
    write(
        evidence / "manifest.json",
        {
            "schema_version": 1,
            "project": {
                "repository": "safal207/ibex-agent-verification",
                "commit": candidate_commit,
            },
            "dut": {
                "repository": "lowRISC/ibex",
                "configuration": "ibex_simple_system",
                "simulator": "verilator",
            },
        },
    )

    write(
        scenario / "gate-request.json",
        {
            "schema_version": 1,
            "change": {
                "request_id": f"demo-{name}-001",
                "actor": {
                    "type": "ai_agent",
                    "name": "codex-demo-agent",
                    "model": "gpt-demo-model",
                },
                "base_commit": "demo-baseline-sha",
                "candidate_commit": candidate_commit,
                "changed_files": ["rtl/ibex_controller.sv"],
                "risk_tags": ["control_flow"],
            },
            "evidence": {
                "trace_comparison": "evidence/trace-comparison.json",
                "baseline_timing": "evidence/baseline-timing.json",
                "candidate_timing": "evidence/candidate-timing.json",
                "baseline_control_flow": "evidence/baseline-control-flow.json",
                "candidate_control_flow": "evidence/candidate-control-flow.json",
                "manifest": "evidence/manifest.json",
            },
            "policy": {
                "max_new_explained_timing_anomalies": 0,
                "max_new_delayed_redirects": 0,
                "manual_review_tags": [
                    "clocking",
                    "reset",
                    "constraints",
                    "security_boundary",
                ],
                "require_ai_model": True,
            },
        },
    )


build_scenario(
    "allow",
    candidate_commit="demo-allow-candidate-sha",
    candidate_causes=(),
)
build_scenario(
    "block",
    candidate_commit="demo-block-candidate-sha",
    candidate_causes=("UNKNOWN",),
)
PY

ibex-av gate-silicon-change \
  --request "${OUT_DIR}/allow/gate-request.json" \
  --report "${OUT_DIR}/allow/gate-decision.json"

set +e
ibex-av gate-silicon-change \
  --request "${OUT_DIR}/block/gate-request.json" \
  --report "${OUT_DIR}/block/gate-decision.json"
block_status=$?
set -e

if [[ "${block_status}" -ne 1 ]]; then
  echo "Expected BLOCK scenario to exit with code 1, got ${block_status}" >&2
  exit 1
fi

python - "${OUT_DIR}" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
allow_path = root / "allow" / "gate-decision.json"
block_path = root / "block" / "gate-decision.json"
allow = json.loads(allow_path.read_text(encoding="utf-8"))
block = json.loads(block_path.read_text(encoding="utf-8"))

if allow.get("decision") != "ALLOW":
    raise SystemExit(f"Expected ALLOW decision, got {allow.get('decision')!r}")
if block.get("decision") != "BLOCK":
    raise SystemExit(f"Expected BLOCK decision, got {block.get('decision')!r}")

block_codes = [reason.get("code") for reason in block.get("reasons", [])]
if "NEW_UNEXPLAINED_TIMING_ANOMALY" not in block_codes:
    raise SystemExit(
        "BLOCK decision did not preserve NEW_UNEXPLAINED_TIMING_ANOMALY evidence"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()

summary = {
    "schema_version": 1,
    "status": "DEMO_PASSED",
    "scenarios": [
        {
            "name": "allow",
            "expected_decision": "ALLOW",
            "actual_decision": allow["decision"],
            "primary_reason": allow["reasons"][0]["code"],
            "decision_report": "allow/gate-decision.json",
            "decision_sha256": sha256(allow_path),
        },
        {
            "name": "block",
            "expected_decision": "BLOCK",
            "actual_decision": block["decision"],
            "primary_reason": "NEW_UNEXPLAINED_TIMING_ANOMALY",
            "decision_report": "block/gate-decision.json",
            "decision_sha256": sha256(block_path),
        },
    ],
}
(root / "demo-summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

echo "Silicon evidence gate demo completed: clean candidate ALLOW, unexplained timing regression BLOCK."
