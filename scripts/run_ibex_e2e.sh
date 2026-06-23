#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IBEX_REF="${IBEX_REF:-022f084096baed0a9b5ebdf697ed2965f13e8ed8}"
IBEX_CONFIG="${IBEX_CONFIG:-small}"
IBEX_DIR="${IBEX_DIR:-$PROJECT_ROOT/third_party/ibex}"
EVIDENCE_DIR="${EVIDENCE_DIR:-$PROJECT_ROOT/artifacts/ibex-e2e}"

if [[ "$IBEX_DIR" != /* ]]; then
  IBEX_DIR="$PROJECT_ROOT/$IBEX_DIR"
fi
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$PROJECT_ROOT/$EVIDENCE_DIR"
fi

RAW_DIR="$EVIDENCE_DIR/raw"
NORMALIZED_DIR="$EVIDENCE_DIR/normalized"
LOG_DIR="$EVIDENCE_DIR/logs"
COMMANDS_FILE="$EVIDENCE_DIR/commands.sh"
TOOL_VERSIONS_FILE="$EVIDENCE_DIR/tool-versions.txt"

rm -rf "$EVIDENCE_DIR"
mkdir -p "$RAW_DIR" "$NORMALIZED_DIR" "$LOG_DIR"
printf '#!/usr/bin/env bash\nset -euo pipefail\n\n' > "$COMMANDS_FILE"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 2
  fi
}

record_command() {
  printf '%q ' "$@" >> "$COMMANDS_FILE"
  printf '\n' >> "$COMMANDS_FILE"
}

run_logged() {
  local name="$1"
  shift
  record_command "$@"
  "$@" >"$LOG_DIR/${name}.stdout" 2>"$LOG_DIR/${name}.stderr"
}

first_line() {
  "$@" 2>&1 | head -n 1 | tr '\n' ' '
}

for command in git make python3 verilator; do
  require_command "$command"
done

# Ubuntu commonly provides a riscv64-prefixed bare-metal toolchain that can
# still emit RV32 code with -march=rv32imc -mabi=ilp32. Ibex's Makefile uses a
# riscv32 prefix, so create local aliases without changing the upstream tree.
if ! command -v riscv32-unknown-elf-gcc >/dev/null 2>&1; then
  require_command riscv64-unknown-elf-gcc
  TOOL_ALIAS_DIR="$EVIDENCE_DIR/toolchain-bin"
  mkdir -p "$TOOL_ALIAS_DIR"
  for tool in gcc objcopy objdump ar as ld nm ranlib readelf size strings strip; do
    source_tool="$(command -v "riscv64-unknown-elf-$tool" || true)"
    if [[ -n "$source_tool" ]]; then
      ln -sf "$source_tool" "$TOOL_ALIAS_DIR/riscv32-unknown-elf-$tool"
    fi
  done
  export PATH="$TOOL_ALIAS_DIR:$PATH"
fi
require_command riscv32-unknown-elf-gcc

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

{
  printf 'python=%s\n' "$(first_line python3 --version)"
  printf 'pip=%s\n' "$(first_line python3 -m pip --version)"
  printf 'fusesoc=%s\n' "$(first_line fusesoc --version)"
  printf 'verilator=%s\n' "$(first_line verilator --version)"
  printf 'riscv_gcc=%s\n' "$(first_line riscv32-unknown-elf-gcc --version)"
  printf 'make=%s\n' "$(first_line make --version)"
  printf 'git=%s\n' "$(first_line git --version)"
} > "$TOOL_VERSIONS_FILE"

pushd "$IBEX_DIR" >/dev/null
IBEX_OPTIONS_STRING="$(python3 util/ibex_config.py "$IBEX_CONFIG" fusesoc_opts)"
read -r -a IBEX_OPTIONS <<< "$IBEX_OPTIONS_STRING"
run_logged build-simulator \
  fusesoc --cores-root=. run --target=sim --setup --build \
  lowrisc:ibex:ibex_simple_system "${IBEX_OPTIONS[@]}"
run_logged build-hello make -C examples/sw/simple_system/hello_test

SIMULATOR="./build/lowrisc_ibex_ibex_simple_system_0/sim-verilator/Vibex_simple_system"
HELLO_ELF="./examples/sw/simple_system/hello_test/hello_test.elf"
if [[ ! -x "$SIMULATOR" ]]; then
  echo "Simulator binary was not produced: $SIMULATOR" >&2
  exit 2
fi
if [[ ! -f "$HELLO_ELF" ]]; then
  echo "Hello-test ELF was not produced: $HELLO_ELF" >&2
  exit 2
fi

record_command "$SIMULATOR" "--meminit=ram,$HELLO_ELF"
"$SIMULATOR" "--meminit=ram,$HELLO_ELF" \
  >"$RAW_DIR/simulator.stdout" 2>"$RAW_DIR/simulator.stderr"

for required_file in \
  trace_core_00000000.log \
  ibex_simple_system.log \
  ibex_simple_system_pcount.csv; do
  if [[ ! -s "$required_file" ]]; then
    echo "Expected simulator output is missing or empty: $required_file" >&2
    exit 2
  fi
  cp "$required_file" "$RAW_DIR/$required_file"
done
cp "$HELLO_ELF" "$RAW_DIR/hello_test.elf"
popd >/dev/null

if ! grep -Fq "Hello simple system" "$RAW_DIR/ibex_simple_system.log"; then
  echo "hello_test output did not contain the expected greeting" >&2
  exit 2
fi

run_logged parse-trace \
  python3 -m ibex_agent_verification parse-ibex-trace \
  --input "$RAW_DIR/trace_core_00000000.log" \
  --output "$NORMALIZED_DIR/architectural.jsonl" \
  --metadata-output "$NORMALIZED_DIR/metadata.jsonl" \
  --timing-output "$NORMALIZED_DIR/timing.jsonl" \
  --report "$NORMALIZED_DIR/parser-report.json"

set +e
record_command python3 -m ibex_agent_verification analyze-timing \
  --input "$NORMALIZED_DIR/timing.jsonl" \
  --report "$NORMALIZED_DIR/timing-report.json"
python3 -m ibex_agent_verification analyze-timing \
  --input "$NORMALIZED_DIR/timing.jsonl" \
  --report "$NORMALIZED_DIR/timing-report.json" \
  >"$LOG_DIR/analyze-timing.stdout" 2>"$LOG_DIR/analyze-timing.stderr"
TIMING_EXIT_CODE=$?
set -e

if [[ "$TIMING_EXIT_CODE" -ne 0 && "$TIMING_EXIT_CODE" -ne 1 ]]; then
  echo "Timing analyzer failed with exit code $TIMING_EXIT_CODE" >&2
  exit 2
fi
printf '%s\n' "$TIMING_EXIT_CODE" > "$EVIDENCE_DIR/timing-exit-code.txt"

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

printf 'Ibex E2E evidence bundle created at %s\n' "$EVIDENCE_DIR"
printf 'Ibex commit: %s\n' "$IBEX_RESOLVED_SHA"
printf 'Timing analyzer exit code: %s\n' "$TIMING_EXIT_CODE"
