#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IBEX_REF="${IBEX_REF:-022f084096baed0a9b5ebdf697ed2965f13e8ed8}"
IBEX_CONFIG="${IBEX_CONFIG:-small}"
IBEX_DIR="${IBEX_DIR:-$PROJECT_ROOT/third_party/ibex}"
EVIDENCE_DIR="${EVIDENCE_DIR:-$PROJECT_ROOT/artifacts/ibex-e2e}"
RISCV_ARCH="${ARCH:-rv32imc_zicsr}"

if [[ "$IBEX_DIR" != /* ]]; then
  IBEX_DIR="$PROJECT_ROOT/$IBEX_DIR"
fi
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$PROJECT_ROOT/$EVIDENCE_DIR"
fi

RAW_DIR="$EVIDENCE_DIR/raw"
NORMALIZED_DIR="$EVIDENCE_DIR/normalized"
LOG_DIR="$EVIDENCE_DIR/logs"
WORK_DIR="$EVIDENCE_DIR/work"
COMMANDS_FILE="$EVIDENCE_DIR/commands.sh"
TOOL_VERSIONS_FILE="$EVIDENCE_DIR/tool-versions.txt"
WAVEFORM_FST="$RAW_DIR/sim.fst"
WAVEFORM_VCD="$WORK_DIR/sim.vcd"
CURRENT_STAGE="initialization"

rm -rf "$EVIDENCE_DIR"
mkdir -p "$RAW_DIR" "$NORMALIZED_DIR" "$LOG_DIR" "$WORK_DIR"
printf '#!/usr/bin/env bash\nset -euo pipefail\n\n' > "$COMMANDS_FILE"

print_log_tail() {
  local path="$1"
  [[ -f "$path" ]] || return 0
  echo
  echo "===== ${path#$EVIDENCE_DIR/} (last 100 lines) ====="
  tail -n 100 "$path" || true
}

print_failure_evidence() {
  local status="$1"
  echo "::error::Ibex E2E failed during stage '$CURRENT_STAGE' with exit code $status" >&2
  echo "Evidence directory: $EVIDENCE_DIR" >&2

  local path
  while IFS= read -r -d '' path; do
    print_log_tail "$path"
  done < <(find "$LOG_DIR" "$RAW_DIR" -maxdepth 1 -type f \
    \( -name '*.stdout' -o -name '*.stderr' -o -name '*.log' \) \
    -print0 2>/dev/null | sort -z)
}

fail() {
  local message="$1"
  echo "::error::$message" >&2
  print_failure_evidence 2
  exit 2
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Missing required command: $1"
  fi
}

record_command() {
  printf '%q ' "$@" >> "$COMMANDS_FILE"
  printf '\n' >> "$COMMANDS_FILE"
}

run_logged() {
  local name="$1"
  shift
  CURRENT_STAGE="$name"
  echo "::group::E2E stage: $name"
  printf 'Command: '
  printf '%q ' "$@"
  printf '\n'
  record_command "$@"

  local status=0
  set +e
  "$@" >"$LOG_DIR/${name}.stdout" 2>"$LOG_DIR/${name}.stderr"
  status=$?
  set -e

  if [[ "$status" -ne 0 ]]; then
    echo "::endgroup::"
    print_failure_evidence "$status"
    exit "$status"
  fi
  echo "::endgroup::"
}

first_line() {
  "$@" 2>&1 | sed -n '1p' | tr '\n' ' '
}

CURRENT_STAGE="checking required commands"
for command in git make python3 verilator fst2vcd; do
  require_command "$command"
done

CURRENT_STAGE="selecting RISC-V toolchain"
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
require_command "$RISCV_CC"
require_command "$RISCV_OBJCOPY"
require_command "$RISCV_OBJDUMP"

CURRENT_STAGE="validating RV32 compiler support"
COMPILER_PROBE="$WORK_DIR/rv32-toolchain-probe.o"
printf 'int probe(void) { return 0; }\n' | \
  "$RISCV_CC" -march="$RISCV_ARCH" -mabi=ilp32 -ffreestanding -x c -c \
  -o "$COMPILER_PROBE" -
rm -f "$COMPILER_PROBE"

CURRENT_STAGE="preparing Ibex checkout"
rm -rf "$IBEX_DIR"
mkdir -p "$(dirname "$IBEX_DIR")"
run_logged git-init git init "$IBEX_DIR"
run_logged git-remote git -C "$IBEX_DIR" remote add origin https://github.com/lowRISC/ibex.git
run_logged git-fetch git -C "$IBEX_DIR" fetch --depth=1 origin "$IBEX_REF"
run_logged git-checkout git -C "$IBEX_DIR" checkout --detach FETCH_HEAD
IBEX_RESOLVED_SHA="$(git -C "$IBEX_DIR" rev-parse HEAD)"

run_logged ibex-python-requirements \
  python3 -m pip install --disable-pip-version-check -r "$IBEX_DIR/python-requirements.txt"
require_command fusesoc

CURRENT_STAGE="recording tool versions"
{
  printf 'python=%s\n' "$(first_line python3 --version)"
  printf 'pip=%s\n' "$(first_line python3 -m pip --version)"
  printf 'fusesoc=%s\n' "$(first_line fusesoc --version)"
  printf 'verilator=%s\n' "$(first_line verilator --version)"
  printf 'fst2vcd_path=%s\n' "$(command -v fst2vcd)"
  printf 'riscv_gcc=%s\n' "$(first_line "$RISCV_CC" --version)"
  printf 'riscv_arch=%s\n' "$RISCV_ARCH"
  printf 'make=%s\n' "$(first_line make --version)"
  printf 'git=%s\n' "$(first_line git --version)"
} > "$TOOL_VERSIONS_FILE"

pushd "$IBEX_DIR" >/dev/null
CURRENT_STAGE="resolving Ibex configuration"
IBEX_OPTIONS_STRING="$(python3 util/ibex_config.py "$IBEX_CONFIG" fusesoc_opts)"
read -r -a IBEX_OPTIONS <<< "$IBEX_OPTIONS_STRING"
run_logged build-simulator \
  fusesoc --cores-root=. run --target=sim --setup --build \
  lowrisc:ibex:ibex_simple_system "${IBEX_OPTIONS[@]}"
run_logged build-hello \
  make -C examples/sw/simple_system/hello_test \
  "CC=$RISCV_CC" \
  "OBJCOPY=$RISCV_OBJCOPY" \
  "OBJDUMP=$RISCV_OBJDUMP" \
  "ARCH=$RISCV_ARCH"

SIMULATOR="./build/lowrisc_ibex_ibex_simple_system_0/sim-verilator/Vibex_simple_system"
HELLO_ELF="./examples/sw/simple_system/hello_test/hello_test.elf"
CURRENT_STAGE="validating build outputs"
if [[ ! -x "$SIMULATOR" ]]; then
  fail "Simulator binary was not produced: $SIMULATOR"
fi
if [[ ! -f "$HELLO_ELF" ]]; then
  fail "Hello-test ELF was not produced: $HELLO_ELF"
fi

CURRENT_STAGE="running simulator with waveform tracing"
record_command "$SIMULATOR" "--meminit=ram,$HELLO_ELF" "--trace=$WAVEFORM_FST"
set +e
"$SIMULATOR" "--meminit=ram,$HELLO_ELF" "--trace=$WAVEFORM_FST" \
  >"$RAW_DIR/simulator.stdout" 2>"$RAW_DIR/simulator.stderr"
SIMULATOR_EXIT_CODE=$?
set -e
if [[ "$SIMULATOR_EXIT_CODE" -ne 0 ]]; then
  print_failure_evidence "$SIMULATOR_EXIT_CODE"
  exit "$SIMULATOR_EXIT_CODE"
fi

CURRENT_STAGE="collecting simulator outputs"
for required_file in \
  trace_core_00000000.log \
  ibex_simple_system.log \
  ibex_simple_system_pcount.csv; do
  if [[ ! -s "$required_file" ]]; then
    fail "Expected simulator output is missing or empty: $required_file"
  fi
  cp "$required_file" "$RAW_DIR/$required_file"
done
if [[ ! -s "$WAVEFORM_FST" ]]; then
  fail "Expected FST waveform is missing or empty: $WAVEFORM_FST"
fi
cp "$HELLO_ELF" "$RAW_DIR/hello_test.elf"
popd >/dev/null

CURRENT_STAGE="validating hello_test output"
if ! grep -Fq "Hello simple system" "$RAW_DIR/ibex_simple_system.log"; then
  fail "hello_test output did not contain the expected greeting"
fi

run_logged parse-trace \
  python3 -m ibex_agent_verification parse-ibex-trace \
  --input "$RAW_DIR/trace_core_00000000.log" \
  --output "$NORMALIZED_DIR/architectural.jsonl" \
  --metadata-output "$NORMALIZED_DIR/metadata.jsonl" \
  --timing-output "$NORMALIZED_DIR/timing.jsonl" \
  --report "$NORMALIZED_DIR/parser-report.json"

run_logged convert-waveform \
  bash -c 'fst2vcd "$1" > "$2"' _ "$WAVEFORM_FST" "$WAVEFORM_VCD"

run_logged enrich-causal-timing \
  python3 -m ibex_agent_verification.causal_hosted \
  --vcd "$WAVEFORM_VCD" \
  --metadata "$NORMALIZED_DIR/metadata.jsonl" \
  --timing "$NORMALIZED_DIR/timing.jsonl" \
  --output "$NORMALIZED_DIR/timing-causal.jsonl" \
  --report "$NORMALIZED_DIR/causal-report.json" \
  --waveform-source "raw/sim.fst"
rm -f "$WAVEFORM_VCD"
rmdir "$WORK_DIR" 2>/dev/null || true

CURRENT_STAGE="analyzing causal timing"
set +e
record_command python3 -m ibex_agent_verification analyze-timing \
  --input "$NORMALIZED_DIR/timing-causal.jsonl" \
  --report "$NORMALIZED_DIR/timing-report.json"
python3 -m ibex_agent_verification analyze-timing \
  --input "$NORMALIZED_DIR/timing-causal.jsonl" \
  --report "$NORMALIZED_DIR/timing-report.json" \
  >"$LOG_DIR/analyze-timing.stdout" 2>"$LOG_DIR/analyze-timing.stderr"
TIMING_EXIT_CODE=$?
set -e

if [[ "$TIMING_EXIT_CODE" -ne 0 && "$TIMING_EXIT_CODE" -ne 1 ]]; then
  fail "Timing analyzer failed with exit code $TIMING_EXIT_CODE"
fi
printf '%s\n' "$TIMING_EXIT_CODE" > "$EVIDENCE_DIR/timing-exit-code.txt"

CURRENT_STAGE="building evidence manifest"
PROJECT_SHA="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
record_command python3 -m ibex_agent_verification.evidence \
  --evidence-dir "$EVIDENCE_DIR" \
  --output "$EVIDENCE_DIR/manifest.json" \
  --project-sha "$PROJECT_SHA" \
  --ibex-requested-ref "$IBEX_REF" \
  --ibex-resolved-sha "$IBEX_RESOLVED_SHA" \
  --ibex-config "$IBEX_CONFIG" \
  --timing-exit-code "$TIMING_EXIT_CODE" \
  --tool-versions-file "$TOOL_VERSIONS_FILE" \
  --commands-file "$COMMANDS_FILE"
python3 -m ibex_agent_verification.evidence \
  --evidence-dir "$EVIDENCE_DIR" \
  --output "$EVIDENCE_DIR/manifest.json" \
  --project-sha "$PROJECT_SHA" \
  --ibex-requested-ref "$IBEX_REF" \
  --ibex-resolved-sha "$IBEX_RESOLVED_SHA" \
  --ibex-config "$IBEX_CONFIG" \
  --timing-exit-code "$TIMING_EXIT_CODE" \
  --tool-versions-file "$TOOL_VERSIONS_FILE" \
  --commands-file "$COMMANDS_FILE"

printf 'Ibex E2E causal evidence bundle created at %s\n' "$EVIDENCE_DIR"
printf 'Ibex commit: %s\n' "$IBEX_RESOLVED_SHA"
printf 'Timing analyzer exit code: %s\n' "$TIMING_EXIT_CODE"
