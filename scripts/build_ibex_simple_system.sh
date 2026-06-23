#!/usr/bin/env bash
set -euo pipefail

IBEX_DIR="${IBEX_DIR:-third_party/ibex}"
IBEX_CONFIG="${IBEX_CONFIG:-small}"

if [[ ! -d "$IBEX_DIR/.git" ]]; then
  echo "Ibex checkout not found at $IBEX_DIR. Run scripts/bootstrap_ibex.sh first." >&2
  exit 2
fi

for command in python3 fusesoc verilator make; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 2
  fi
done

if ! command -v riscv32-unknown-elf-gcc >/dev/null 2>&1 && \
   ! command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then
  echo "RISC-V GCC toolchain not found in PATH." >&2
  echo "Install a compatible toolchain and follow upstream Ibex Simple System documentation." >&2
  exit 2
fi

pushd "$IBEX_DIR" >/dev/null
python3 -m pip install -U -r python-requirements.txt
fusesoc --cores-root=. run --target=sim --setup --build \
  lowrisc:ibex:ibex_simple_system $(util/ibex_config.py "$IBEX_CONFIG" fusesoc_opts)
make -C examples/sw/simple_system/hello_test
popd >/dev/null

echo "Ibex Simple System build completed for config: $IBEX_CONFIG"
echo "Next: run the upstream simulator and preserve trace_core_00000000.log as raw evidence."
