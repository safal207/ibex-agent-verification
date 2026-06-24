#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IBEX_REF="${IBEX_REF:-022f084096baed0a9b5ebdf697ed2965f13e8ed8}"
IBEX_CONFIG="${IBEX_CONFIG:-small}"
WORK_ROOT="${WORK_ROOT:-$PROJECT_ROOT/third_party/ibex-real-rtl-gate}"
EVIDENCE_DIR="${EVIDENCE_DIR:-$PROJECT_ROOT/artifacts/real-rtl-gate-demo}"
RISCV_ARCH="${ARCH:-rv32imc_zicsr}"

if [[ "$WORK_ROOT" != /* ]]; then
  WORK_ROOT="$PROJECT_ROOT/$WORK_ROOT"
fi
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$PROJECT_ROOT/$EVIDENCE_DIR"
fi

BASELINE_IBEX_DIR="$WORK_ROOT/baseline"
CANDIDATE_IBEX_DIR="$WORK_ROOT/candidate"
BUILD_LOG_DIR="$EVIDENCE_DIR/build-logs"
GATE_DIR="$EVIDENCE_DIR/gate"
SIM_DIR="$EVIDENCE_DIR/simulators"
PATCH_FILE="$PROJECT_ROOT/examples/rtl_gate/instruction_memory_delay.patch"
FIRMWARE_SOURCE="$PROJECT_ROOT/examples/firmware_gate/firmware_gate_baseline.c"
CURRENT_STAGE="initialization"

rm -rf "$WORK_ROOT" "$EVIDENCE_DIR"
mkdir -p "$WORK_ROOT" "$BUILD_LOG_DIR" "$GATE_DIR/evidence" "$SIM_DIR"

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
  echo "::group::Real RTL gate stage: $name"
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

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
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

[[ -f "$PATCH_FILE" ]] || fail "Missing RTL patch: $PATCH_FILE"
[[ -f "$FIRMWARE_SOURCE" ]] || fail "Missing firmware source: $FIRMWARE_SOURCE"

CURRENT_STAGE="validating RV32 compiler support"
printf 'int probe(void) { return 0; }\n' | \
  "$RISCV_CC" -march="$RISCV_ARCH" -mabi=ilp32 -ffreestanding -x c -c \
  -o "$EVIDENCE_DIR/rv32-toolchain-probe.o" -
rm -f "$EVIDENCE_DIR/rv32-toolchain-probe.o"

run_logged git-init git init "$BASELINE_IBEX_DIR"
run_logged git-remote \
  git -C "$BASELINE_IBEX_DIR" remote add origin https://github.com/lowRISC/ibex.git
run_logged git-fetch \
  git -C "$BASELINE_IBEX_DIR" fetch --depth=1 origin "$IBEX_REF"
run_logged git-checkout \
  git -C "$BASELINE_IBEX_DIR" checkout --detach FETCH_HEAD
IBEX_RESOLVED_SHA="$(git -C "$BASELINE_IBEX_DIR" rev-parse HEAD)"
PROJECT_SHA="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"

run_logged candidate-worktree \
  git -C "$BASELINE_IBEX_DIR" worktree add --detach \
  "$CANDIDATE_IBEX_DIR" "$IBEX_RESOLVED_SHA"

run_logged ibex-python-requirements \
  python3 -m pip install --disable-pip-version-check \
  -r "$BASELINE_IBEX_DIR/python-requirements.txt"
require_command fusesoc

build_simulator() {
  local checkout="$1"
  local label="$2"
  local output="$3"

  pushd "$checkout" >/dev/null
  local options_string
  options_string="$(python3 util/ibex_config.py "$IBEX_CONFIG" fusesoc_opts)"
  read -r -a options <<< "$options_string"
  run_logged "build-simulator-$label" \
    fusesoc --cores-root=. run --target=sim --setup --build \
    lowrisc:ibex:ibex_simple_system "${options[@]}"
  popd >/dev/null

  local built="$checkout/build/lowrisc_ibex_ibex_simple_system_0/sim-verilator/Vibex_simple_system"
  [[ -x "$built" ]] || fail "Simulator binary was not produced for $label"
  cp "$built" "$output"
  chmod +x "$output"
}

BASELINE_SIM="$SIM_DIR/Vibex_simple_system-baseline"
CANDIDATE_SIM="$SIM_DIR/Vibex_simple_system-candidate"
build_simulator "$BASELINE_IBEX_DIR" "baseline" "$BASELINE_SIM"

run_logged rtl-patch-check \
  git -C "$CANDIDATE_IBEX_DIR" apply --check "$PATCH_FILE"
run_logged rtl-patch-apply \
  git -C "$CANDIDATE_IBEX_DIR" apply "$PATCH_FILE"

git -C "$CANDIDATE_IBEX_DIR" diff --check || fail "Candidate RTL diff failed git diff --check"
git -C "$CANDIDATE_IBEX_DIR" diff -- \
  examples/simple_system/rtl/ibex_simple_system.sv \
  >"$GATE_DIR/evidence/candidate-rtl.patch"
[[ -s "$GATE_DIR/evidence/candidate-rtl.patch" ]] || fail "Candidate RTL diff is empty"
grep -Fq '.BExtraDelay(1)' \
  "$CANDIDATE_IBEX_DIR/examples/simple_system/rtl/ibex_simple_system.sv" || \
  fail "Candidate RTL does not contain the intended instruction-memory delay"

build_simulator "$CANDIDATE_IBEX_DIR" "candidate" "$CANDIDATE_SIM"

PROGRAM="rtl_gate_firmware"
PROGRAM_DIR="$BASELINE_IBEX_DIR/examples/sw/simple_system/$PROGRAM"
mkdir -p "$PROGRAM_DIR"
cp "$FIRMWARE_SOURCE" "$PROGRAM_DIR/$PROGRAM.c"
cat >"$PROGRAM_DIR/Makefile" <<MAKEFILE
# SPDX-License-Identifier: Apache-2.0
PROGRAM = $PROGRAM
PROGRAM_DIR := \$(shell dirname \$(realpath \$(lastword \$(MAKEFILE_LIST))))
EXTRA_SRCS :=
include \${PROGRAM_DIR}/../common/common.mk
MAKEFILE

run_logged build-firmware \
  make -C "$PROGRAM_DIR" \
  "CC=$RISCV_CC" \
  "OBJCOPY=$RISCV_OBJCOPY" \
  "OBJDUMP=$RISCV_OBJDUMP" \
  "ARCH=$RISCV_ARCH" \
  "PROGRAM_CFLAGS=-fno-unroll-loops"
run_logged disassemble-firmware \
  make -C "$PROGRAM_DIR" disassemble \
  "CC=$RISCV_CC" \
  "OBJCOPY=$RISCV_OBJCOPY" \
  "OBJDUMP=$RISCV_OBJDUMP" \
  "ARCH=$RISCV_ARCH" \
  "PROGRAM_CFLAGS=-fno-unroll-loops"

FIRMWARE_ELF="$PROGRAM_DIR/$PROGRAM.elf"
FIRMWARE_DIS="$PROGRAM_DIR/$PROGRAM.dis"
[[ -f "$FIRMWARE_ELF" ]] || fail "Firmware ELF was not produced"
[[ -f "$FIRMWARE_DIS" ]] || fail "Firmware disassembly was not produced"

run_scenario() {
  local scenario="$1"
  local simulator="$2"
  local scenario_dir="$EVIDENCE_DIR/$scenario"
  local raw_dir="$scenario_dir/raw"
  local normalized_dir="$scenario_dir/normalized"
  local runtime_dir="$scenario_dir/runtime"
  local work_dir="$scenario_dir/work"

  mkdir -p "$raw_dir" "$normalized_dir" "$runtime_dir" "$work_dir"

  CURRENT_STAGE="simulate-$scenario"
  echo "::group::Real RTL simulation: $scenario"
  set +e
  (
    cd "$runtime_dir"
    "$simulator" --meminit="ram,$FIRMWARE_ELF" --trace="$raw_dir/sim.fst"
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
    [[ -s "$runtime_dir/$required_file" ]] || \
      fail "Missing simulator output for $scenario: $required_file"
    cp "$runtime_dir/$required_file" "$raw_dir/$required_file"
  done
  rm -rf "$runtime_dir"

  [[ -s "$raw_dir/sim.fst" ]] || fail "Missing waveform for $scenario"
  cp "$FIRMWARE_SOURCE" "$raw_dir/$PROGRAM.c"
  cp "$FIRMWARE_ELF" "$raw_dir/$PROGRAM.elf"
  cp "$FIRMWARE_DIS" "$raw_dir/$PROGRAM.dis"
  printf '%s\n' "$(sha256_file "$simulator")" >"$raw_dir/simulator.sha256"

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

run_scenario "baseline" "$BASELINE_SIM"
run_scenario "candidate-a" "$CANDIDATE_SIM"
run_scenario "candidate-b" "$CANDIDATE_SIM"

ibex-av compare \
  --expected "$EVIDENCE_DIR/baseline/normalized/architectural.jsonl" \
  --actual "$EVIDENCE_DIR/candidate-a/normalized/architectural.jsonl" \
  --report "$GATE_DIR/evidence/trace-comparison.json"
ibex-av compare \
  --expected "$EVIDENCE_DIR/candidate-a/normalized/architectural.jsonl" \
  --actual "$EVIDENCE_DIR/candidate-b/normalized/architectural.jsonl" \
  --report "$GATE_DIR/evidence/candidate-replay-comparison.json"

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
  "$PATCH_FILE" \
  "$FIRMWARE_SOURCE" \
  "$FIRMWARE_ELF" \
  "$BASELINE_SIM" \
  "$CANDIDATE_SIM" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

(
    gate_dir_raw,
    project_sha,
    ibex_sha,
    patch_raw,
    firmware_source_raw,
    firmware_elf_raw,
    baseline_sim_raw,
    candidate_sim_raw,
) = sys.argv[1:]

gate_dir = Path(gate_dir_raw)
evidence_dir = gate_dir / "evidence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


patch = Path(patch_raw)
firmware_source = Path(firmware_source_raw)
firmware_elf = Path(firmware_elf_raw)
baseline_sim = Path(baseline_sim_raw)
candidate_sim = Path(candidate_sim_raw)

manifest = {
    "schema_version": 1,
    "project": {
        "repository": "safal207/ibex-agent-verification",
        "commit": project_sha,
    },
    "dut": {
        "repository": "lowRISC/ibex",
        "baseline_commit": ibex_sha,
        "candidate_base_commit": ibex_sha,
        "configuration": "small",
        "simulator": "verilator",
        "rtl_patch": {
            "path": "examples/rtl_gate/instruction_memory_delay.patch",
            "sha256": sha256(patch),
        },
        "baseline_simulator_sha256": sha256(baseline_sim),
        "candidate_simulator_sha256": sha256(candidate_sim),
    },
    "firmware": {
        "source": firmware_source.name,
        "source_sha256": sha256(firmware_source),
        "elf_sha256": sha256(firmware_elf),
    },
    "runs": {
        "baseline": "baseline",
        "candidate": "candidate-a",
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
        "request_id": "real-rtl-instruction-memory-delay-001",
        "actor": {
            "type": "ai_agent",
            "name": "chatgpt-codex-collaboration",
            "model": "GPT-5.5 Thinking",
        },
        "base_commit": ibex_sha,
        "candidate_commit": project_sha,
        "changed_files": [
            "examples/simple_system/rtl/ibex_simple_system.sv"
        ],
        "risk_tags": ["rtl", "instruction_fetch", "performance"],
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
  fail "Expected real RTL candidate to be BLOCKED (exit 1), got $GATE_STATUS"
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
baseline_control = load(root / "baseline/normalized/branch-redirect-report.json")
candidate_control = load(root / "candidate-a/normalized/branch-redirect-report.json")
functional = load(root / "gate/evidence/trace-comparison.json")
replay = load(root / "gate/evidence/candidate-replay-comparison.json")
decision = load(root / "gate/gate-decision.json")
manifest = load(root / "gate/evidence/manifest.json")

if functional.get("status") != "MATCH":
    raise SystemExit("Baseline and candidate architectural traces did not match")
if replay.get("status") != "MATCH":
    raise SystemExit("Candidate replay architectural traces did not match")
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
    "status": "REAL_RTL_GATE_DEMO_PASSED",
    "ibex_commit": manifest["dut"]["baseline_commit"],
    "project_commit": manifest["project"]["commit"],
    "rtl_patch": manifest["dut"]["rtl_patch"],
    "functional_equivalence": {
        "status": functional["status"],
        "events": functional["actual_events"],
    },
    "candidate_replay": {
        "status": replay["status"],
        "events": replay["actual_events"],
    },
    "baseline": {
        "instructions": baseline_parser["instructions"],
        "first_cycle": baseline_parser["first_cycle"],
        "last_cycle": baseline_parser["last_cycle"],
        "timing_anomalies": baseline_timing["anomalies"],
        "causes": cause_counts(baseline_timing),
        "delayed_redirects": baseline_control["delayed_redirects"],
    },
    "candidate": {
        "instructions": candidate_parser["instructions"],
        "first_cycle": candidate_parser["first_cycle"],
        "last_cycle": candidate_parser["last_cycle"],
        "timing_anomalies": candidate_timing["anomalies"],
        "causes": cause_counts(candidate_timing),
        "delayed_redirects": candidate_control["delayed_redirects"],
    },
    "gate": {
        "decision": decision["decision"],
        "reason_codes": reason_codes,
        "metrics": decision["metrics"],
        "decision_sha256": sha256(root / "gate/gate-decision.json"),
    },
    "simulators": {
        "baseline_sha256": manifest["dut"]["baseline_simulator_sha256"],
        "candidate_sha256": manifest["dut"]["candidate_simulator_sha256"],
    },
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
rtl_patch_sha256=$(sha256_file "$PATCH_FILE")
EOF

rm -rf "$WORK_ROOT"

printf 'Real RTL gate evidence bundle created at %s\n' "$EVIDENCE_DIR"
printf 'Baseline/candidate architectural status: MATCH\n'
printf 'Candidate replay status: MATCH\n'
printf 'Gate decision: BLOCK\n'
