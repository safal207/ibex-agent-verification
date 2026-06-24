#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IBEX_REF="${IBEX_REF:-022f084096baed0a9b5ebdf697ed2965f13e8ed8}"
IBEX_CONFIG="${IBEX_CONFIG:-small}"
IBEX_DIR="${IBEX_DIR:-$PROJECT_ROOT/third_party/ibex-real-firmware-gate}"
EVIDENCE_DIR="${EVIDENCE_DIR:-$PROJECT_ROOT/artifacts/real-firmware-gate-demo}"
RISCV_ARCH="${ARCH:-rv32imc_zicsr}"

if [[ "$IBEX_DIR" != /* ]]; then
  IBEX_DIR="$PROJECT_ROOT/$IBEX_DIR"
fi
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$PROJECT_ROOT/$EVIDENCE_DIR"
fi

BUILD_LOG_DIR="$EVIDENCE_DIR/build-logs"
GATE_DIR="$EVIDENCE_DIR/gate"
CURRENT_STAGE="initialization"

rm -rf "$EVIDENCE_DIR"
mkdir -p "$BUILD_LOG_DIR" "$GATE_DIR/evidence"

fail() {
  echo "::error::$1" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

run_logged() {
  local name="$1"
  shift
  CURRENT_STAGE="$name"
  echo "::group::Real firmware gate stage: $name"
  printf 'Command: '
  printf '%q ' "$@"
  printf '\n'

  local status=0
  set +e
  "$@" >"$BUILD_LOG_DIR/${name}.stdout" 2>"$BUILD_LOG_DIR/${name}.stderr"
  status=$?
  set -e

  if [[ "$status" -ne 0 ]]; then
    echo "::endgroup::"
    echo "::error::Stage '$name' failed with exit code $status" >&2
    tail -n 100 "$BUILD_LOG_DIR/${name}.stdout" 2>/dev/null || true
    tail -n 100 "$BUILD_LOG_DIR/${name}.stderr" 2>/dev/null || true
    exit "$status"
  fi
  echo "::endgroup::"
}

for command in git make python3 verilator fst2vcd; do
  require_command "$command"
done

if command -v riscv32-unknown-elf-gcc >/dev/null 2>&1; then
  RISCV_PREFIX="riscv32-unknown-elf"
elif command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then
  RISCV_PREFIX="riscv64-unknown-elf"
else
  fail "Missing bare-metal RISC-V GCC toolchain"
fi
RISCV_CC="${RISCV_PREFIX}-gcc"
RISCV_OBJCOPY="${RISCV_PREFIX}-objcopy"
RISCV_OBJDUMP="${RISCV_PREFIX}-objdump"

CURRENT_STAGE="validating RV32 compiler support"
printf 'int probe(void) { return 0; }\n' | \
  "$RISCV_CC" -march="$RISCV_ARCH" -mabi=ilp32 -ffreestanding -x c -c \
  -o "$EVIDENCE_DIR/rv32-toolchain-probe.o" -
rm -f "$EVIDENCE_DIR/rv32-toolchain-probe.o"

rm -rf "$IBEX_DIR"
mkdir -p "$(dirname "$IBEX_DIR")"
run_logged git-init git init "$IBEX_DIR"
run_logged git-remote git -C "$IBEX_DIR" remote add origin https://github.com/lowRISC/ibex.git
run_logged git-fetch git -C "$IBEX_DIR" fetch --depth=1 origin "$IBEX_REF"
run_logged git-checkout git -C "$IBEX_DIR" checkout --detach FETCH_HEAD
IBEX_RESOLVED_SHA="$(git -C "$IBEX_DIR" rev-parse HEAD)"
PROJECT_SHA="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"

run_logged ibex-python-requirements \
  python3 -m pip install --disable-pip-version-check -r "$IBEX_DIR/python-requirements.txt"
require_command fusesoc

pushd "$IBEX_DIR" >/dev/null
IBEX_OPTIONS_STRING="$(python3 util/ibex_config.py "$IBEX_CONFIG" fusesoc_opts)"
read -r -a IBEX_OPTIONS <<< "$IBEX_OPTIONS_STRING"
run_logged build-simulator \
  fusesoc --cores-root=. run --target=sim --setup --build \
  lowrisc:ibex:ibex_simple_system "${IBEX_OPTIONS[@]}"
popd >/dev/null

SIMULATOR="$IBEX_DIR/build/lowrisc_ibex_ibex_simple_system_0/sim-verilator/Vibex_simple_system"
[[ -x "$SIMULATOR" ]] || fail "Simulator binary was not produced: $SIMULATOR"

install_firmware() {
  local program="$1"
  local source="$2"
  local program_dir="$IBEX_DIR/examples/sw/simple_system/$program"

  mkdir -p "$program_dir"
  cp "$source" "$program_dir/$program.c"
  cat >"$program_dir/Makefile" <<MAKEFILE
# SPDX-License-Identifier: Apache-2.0
PROGRAM = $program
PROGRAM_DIR := \$(shell dirname \$(realpath \$(lastword \$(MAKEFILE_LIST))))
EXTRA_SRCS :=
include \${PROGRAM_DIR}/../common/common.mk
MAKEFILE

  run_logged "build-$program" \
    make -C "$program_dir" \
    "CC=$RISCV_CC" \
    "OBJCOPY=$RISCV_OBJCOPY" \
    "OBJDUMP=$RISCV_OBJDUMP" \
    "ARCH=$RISCV_ARCH" \
    "PROGRAM_CFLAGS=-fno-unroll-loops"
  run_logged "disassemble-$program" \
    make -C "$program_dir" disassemble \
    "CC=$RISCV_CC" \
    "OBJCOPY=$RISCV_OBJCOPY" \
    "OBJDUMP=$RISCV_OBJDUMP" \
    "ARCH=$RISCV_ARCH" \
    "PROGRAM_CFLAGS=-fno-unroll-loops"
}

BASELINE_PROGRAM="firmware_gate_baseline"
CANDIDATE_PROGRAM="firmware_gate_candidate"
BASELINE_SOURCE="$PROJECT_ROOT/examples/firmware_gate/${BASELINE_PROGRAM}.c"
CANDIDATE_SOURCE="$PROJECT_ROOT/examples/firmware_gate/${CANDIDATE_PROGRAM}.c"

[[ -f "$BASELINE_SOURCE" ]] || fail "Missing baseline firmware source"
[[ -f "$CANDIDATE_SOURCE" ]] || fail "Missing candidate firmware source"

install_firmware "$BASELINE_PROGRAM" "$BASELINE_SOURCE"
install_firmware "$CANDIDATE_PROGRAM" "$CANDIDATE_SOURCE"

BASELINE_ELF="$IBEX_DIR/examples/sw/simple_system/$BASELINE_PROGRAM/${BASELINE_PROGRAM}.elf"
CANDIDATE_ELF="$IBEX_DIR/examples/sw/simple_system/$CANDIDATE_PROGRAM/${CANDIDATE_PROGRAM}.elf"
[[ -f "$BASELINE_ELF" ]] || fail "Baseline ELF was not produced"
[[ -f "$CANDIDATE_ELF" ]] || fail "Candidate ELF was not produced"

run_scenario() {
  local scenario="$1"
  local program="$2"
  local elf="$3"
  local source="$4"
  local scenario_dir="$EVIDENCE_DIR/$scenario"
  local raw_dir="$scenario_dir/raw"
  local normalized_dir="$scenario_dir/normalized"
  local work_dir="$scenario_dir/work"

  mkdir -p "$raw_dir" "$normalized_dir" "$work_dir"
  rm -f \
    "$IBEX_DIR/trace_core_00000000.log" \
    "$IBEX_DIR/ibex_simple_system.log" \
    "$IBEX_DIR/ibex_simple_system_pcount.csv"

  CURRENT_STAGE="simulate-$scenario"
  echo "::group::Real firmware simulation: $scenario"
  set +e
  (
    cd "$IBEX_DIR"
    "$SIMULATOR" --meminit="ram,$elf" --trace="$raw_dir/sim.fst"
  ) >"$raw_dir/simulator.stdout" 2>"$raw_dir/simulator.stderr"
  local simulator_status=$?
  set -e
  echo "::endgroup::"
  if [[ "$simulator_status" -ne 0 ]]; then
    tail -n 100 "$raw_dir/simulator.stdout" || true
    tail -n 100 "$raw_dir/simulator.stderr" || true
    fail "Simulator failed for $scenario with exit code $simulator_status"
  fi

  for required_file in \
    trace_core_00000000.log \
    ibex_simple_system.log \
    ibex_simple_system_pcount.csv; do
    [[ -s "$IBEX_DIR/$required_file" ]] || \
      fail "Missing simulator output for $scenario: $required_file"
    cp "$IBEX_DIR/$required_file" "$raw_dir/$required_file"
  done
  [[ -s "$raw_dir/sim.fst" ]] || fail "Missing waveform for $scenario"

  cp "$elf" "$raw_dir/$program.elf"
  cp "$source" "$raw_dir/$program.c"
  cp "${elf%.elf}.dis" "$raw_dir/$program.dis"

  grep -Fq "Firmware gate result" "$raw_dir/ibex_simple_system.log" || \
    fail "Firmware result marker missing for $scenario"
  grep -Fq "00000100" "$raw_dir/ibex_simple_system.log" || \
    fail "Firmware result value missing for $scenario"

  ibex-av parse-ibex-trace \
    --input "$raw_dir/trace_core_00000000.log" \
    --output "$normalized_dir/architectural.jsonl" \
    --metadata-output "$normalized_dir/metadata.jsonl" \
    --timing-output "$normalized_dir/timing.jsonl" \
    --report "$normalized_dir/parser-report.json"

  fst2vcd "$raw_dir/sim.fst" >"$work_dir/sim.vcd"
  python3 -m ibex_agent_verification.causal_hosted \
    --vcd "$work_dir/sim.vcd" \
    --metadata "$normalized_dir/metadata.jsonl" \
    --timing "$normalized_dir/timing.jsonl" \
    --output "$normalized_dir/timing-causal.jsonl" \
    --report "$normalized_dir/causal-report.json" \
    --waveform-source "raw/sim.fst"
  rm -f "$work_dir/sim.vcd"
  rmdir "$work_dir" 2>/dev/null || true

  set +e
  ibex-av analyze-timing \
    --input "$normalized_dir/timing-causal.jsonl" \
    --report "$normalized_dir/timing-report.json"
  local timing_status=$?
  set -e
  if [[ "$timing_status" -ne 0 && "$timing_status" -ne 1 ]]; then
    fail "Timing analyzer failed for $scenario with exit code $timing_status"
  fi
  printf '%s\n' "$timing_status" >"$scenario_dir/timing-exit-code.txt"

  python3 -m ibex_agent_verification.control_flow \
    --input "$raw_dir/trace_core_00000000.log" \
    --output "$normalized_dir/branch-redirects.jsonl" \
    --report "$normalized_dir/branch-redirect-report.json"
}

run_scenario "baseline" "$BASELINE_PROGRAM" "$BASELINE_ELF" "$BASELINE_SOURCE"
run_scenario "candidate-a" "$CANDIDATE_PROGRAM" "$CANDIDATE_ELF" "$CANDIDATE_SOURCE"
run_scenario "candidate-b" "$CANDIDATE_PROGRAM" "$CANDIDATE_ELF" "$CANDIDATE_SOURCE"

ibex-av compare \
  --expected "$EVIDENCE_DIR/candidate-a/normalized/architectural.jsonl" \
  --actual "$EVIDENCE_DIR/candidate-b/normalized/architectural.jsonl" \
  --report "$GATE_DIR/evidence/trace-comparison.json"

cp "$EVIDENCE_DIR/baseline/normalized/timing-report.json" \
  "$GATE_DIR/evidence/baseline-timing.json"
cp "$EVIDENCE_DIR/candidate-a/normalized/timing-report.json" \
  "$GATE_DIR/evidence/candidate-timing.json"
cp "$EVIDENCE_DIR/baseline/normalized/branch-redirect-report.json" \
  "$GATE_DIR/evidence/baseline-control-flow.json"
cp "$EVIDENCE_DIR/candidate-a/normalized/branch-redirect-report.json" \
  "$GATE_DIR/evidence/candidate-control-flow.json"

python3 - \
  "$GATE_DIR" \
  "$PROJECT_SHA" \
  "$IBEX_RESOLVED_SHA" \
  "$BASELINE_SOURCE" \
  "$CANDIDATE_SOURCE" \
  "$BASELINE_ELF" \
  "$CANDIDATE_ELF" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

(
    gate_dir_raw,
    project_sha,
    ibex_sha,
    baseline_source_raw,
    candidate_source_raw,
    baseline_elf_raw,
    candidate_elf_raw,
) = sys.argv[1:]

gate_dir = Path(gate_dir_raw)
evidence_dir = gate_dir / "evidence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


baseline_source = Path(baseline_source_raw)
candidate_source = Path(candidate_source_raw)
baseline_elf = Path(baseline_elf_raw)
candidate_elf = Path(candidate_elf_raw)

manifest = {
    "schema_version": 1,
    "project": {
        "repository": "safal207/ibex-agent-verification",
        "commit": project_sha,
    },
    "dut": {
        "repository": "lowRISC/ibex",
        "resolved_commit": ibex_sha,
        "configuration": "small",
        "simulator": "verilator",
    },
    "firmware": {
        "baseline": {
            "source": baseline_source.name,
            "source_sha256": sha256(baseline_source),
            "elf_sha256": sha256(baseline_elf),
        },
        "candidate": {
            "source": candidate_source.name,
            "source_sha256": sha256(candidate_source),
            "elf_sha256": sha256(candidate_elf),
        },
    },
    "runs": {
        "baseline": "baseline",
        "candidate_oracle": "candidate-a",
        "candidate_replay": "candidate-b",
    },
}
(evidence_dir / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

request = {
    "schema_version": 1,
    "change": {
        "request_id": "real-firmware-memory-read-regression-001",
        "actor": {
            "type": "ai_agent",
            "name": "chatgpt-codex-collaboration",
            "model": "GPT-5.5 Thinking",
        },
        "base_commit": project_sha,
        "candidate_commit": project_sha,
        "changed_files": [
            "examples/firmware_gate/firmware_gate_candidate.c"
        ],
        "risk_tags": ["firmware", "performance", "memory_access"],
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
        "manual_review_tags": [],
        "require_ai_model": True,
    },
}
(gate_dir / "gate-request.json").write_text(
    json.dumps(request, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

set +e
ibex-av gate-silicon-change \
  --request "$GATE_DIR/gate-request.json" \
  --report "$GATE_DIR/gate-decision.json"
GATE_STATUS=$?
set -e

if [[ "$GATE_STATUS" -ne 1 ]]; then
  fail "Expected real firmware candidate to be BLOCKED (exit 1), got $GATE_STATUS"
fi

python3 - "$EVIDENCE_DIR" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def cause_counts(report: dict) -> dict[str, int]:
    counts = Counter()
    for finding in report.get("findings", []):
        if finding.get("status") == "DELAY_ANOMALY":
            counts[finding.get("primary_cause") or "UNKNOWN"] += 1
    return dict(sorted(counts.items()))


baseline_parser = load(root / "baseline/normalized/parser-report.json")
candidate_parser = load(root / "candidate-a/normalized/parser-report.json")
baseline_timing = load(root / "baseline/normalized/timing-report.json")
candidate_timing = load(root / "candidate-a/normalized/timing-report.json")
comparison = load(root / "gate/evidence/trace-comparison.json")
decision = load(root / "gate/gate-decision.json")
manifest = load(root / "gate/evidence/manifest.json")

if comparison.get("status") != "MATCH":
    raise SystemExit("Candidate oracle/replay architectural traces did not match")
if decision.get("decision") != "BLOCK":
    raise SystemExit(f"Expected BLOCK decision, got {decision.get('decision')!r}")
if decision.get("checks", {}).get("evidence_commit_bound") is not True:
    raise SystemExit("Gate evidence was not bound to the candidate commit")

reason_codes = [reason.get("code") for reason in decision.get("reasons", [])]
regression_codes = {
    "NEW_UNEXPLAINED_TIMING_ANOMALY",
    "EXPLAINED_TIMING_REGRESSION_LIMIT_EXCEEDED",
    "BRANCH_REDIRECT_DELAY_LIMIT_EXCEEDED",
}
if not regression_codes.intersection(reason_codes):
    raise SystemExit(
        "BLOCK decision did not include a timing or redirect regression reason: "
        + ", ".join(str(code) for code in reason_codes)
    )

summary = {
    "schema_version": 1,
    "status": "REAL_FIRMWARE_GATE_DEMO_PASSED",
    "ibex_commit": manifest["dut"]["resolved_commit"],
    "project_commit": manifest["project"]["commit"],
    "candidate_replay": {
        "trace_status": comparison["status"],
        "events": comparison["actual_events"],
    },
    "baseline": {
        "instructions": baseline_parser["instructions"],
        "first_cycle": baseline_parser["first_cycle"],
        "last_cycle": baseline_parser["last_cycle"],
        "timing_anomalies": baseline_timing["anomalies"],
        "causes": cause_counts(baseline_timing),
    },
    "candidate": {
        "instructions": candidate_parser["instructions"],
        "first_cycle": candidate_parser["first_cycle"],
        "last_cycle": candidate_parser["last_cycle"],
        "timing_anomalies": candidate_timing["anomalies"],
        "causes": cause_counts(candidate_timing),
    },
    "gate": {
        "decision": decision["decision"],
        "reason_codes": reason_codes,
        "metrics": decision["metrics"],
        "decision_sha256": sha256(root / "gate/gate-decision.json"),
    },
    "firmware": manifest["firmware"],
}
(root / "demo-summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

cat >"$EVIDENCE_DIR/tool-versions.txt" <<EOF
python=$(python3 --version 2>&1)
verilator=$(verilator --version 2>&1 | head -n 1)
riscv_gcc=$($RISCV_CC --version 2>&1 | head -n 1)
fusesoc=$(fusesoc --version 2>&1 | head -n 1)
ibex_commit=$IBEX_RESOLVED_SHA
project_commit=$PROJECT_SHA
EOF

printf 'Real firmware gate evidence bundle created at %s\n' "$EVIDENCE_DIR"
printf 'Candidate replay trace status: MATCH\n'
printf 'Gate decision: BLOCK\n'
