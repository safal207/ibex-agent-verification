# Pinned Ibex Verilator E2E Run

This workflow turns the trace adapter into a reproducible simulator experiment.
It checks out an explicitly pinned lowRISC/ibex revision, builds the Ibex Simple
System and its `hello_test` program, runs the program under Verilator, parses the
generated instruction trace, analyzes retirement-cycle gaps, and publishes an
evidence bundle.

## Pinned device under test

Default Ibex revision:

```text
022f084096baed0a9b5ebdf697ed2965f13e8ed8
```

Default configuration:

```text
small
```

Both values can be overridden locally with `IBEX_REF` and `IBEX_CONFIG`, but the
GitHub Actions workflow keeps them explicit so a run can be reproduced later.

## GitHub Actions

Workflow:

```text
.github/workflows/ibex-e2e.yml
```

It runs on Ubuntu 24.04, installs Verilator and a bare-metal RISC-V compiler,
then executes:

```bash
./scripts/run_ibex_e2e.sh
```

The workflow can be started manually and also runs when E2E-related files change.
It uploads `artifacts/ibex-e2e/` even after a failed step when partial evidence is
available.

## Local prerequisites

- Python 3.11+
- Git
- Make and a C++ build toolchain
- Verilator
- libelf development files
- srecord
- a bare-metal RISC-V GCC toolchain

The upstream software Makefile expects `riscv32-unknown-elf-*`. If only a
`riscv64-unknown-elf-*` toolchain is installed, the runner creates temporary
local aliases and still passes the explicit RV32 architecture and ABI flags
used by upstream Ibex.

## Successful-run contract

The run is successful only when all of the following are true:

1. the requested Ibex ref resolves to a concrete commit;
2. FuseSoC builds `Vibex_simple_system`;
3. the upstream `hello_test.elf` is built;
4. the simulator exits successfully;
5. `ibex_simple_system.log` contains `Hello simple system`;
6. the raw instruction trace and performance-counter CSV exist and are non-empty;
7. the repository parser produces architectural, metadata, and timing JSONL;
8. the timing analyzer returns either `0` (no anomaly) or `1` (anomaly detected), never an input/execution error;
9. a manifest is written with tool versions and SHA-256 for every evidence file.

## Evidence bundle

```text
artifacts/ibex-e2e/
├── commands.sh
├── manifest.json
├── timing-exit-code.txt
├── tool-versions.txt
├── logs/
│   ├── build-simulator.stdout
│   ├── build-simulator.stderr
│   ├── build-hello.stdout
│   ├── build-hello.stderr
│   └── ...
├── raw/
│   ├── hello_test.elf
│   ├── ibex_simple_system.log
│   ├── ibex_simple_system_pcount.csv
│   ├── simulator.stdout
│   ├── simulator.stderr
│   └── trace_core_00000000.log
└── normalized/
    ├── architectural.jsonl
    ├── metadata.jsonl
    ├── timing.jsonl
    ├── parser-report.json
    └── timing-report.json
```

`manifest.json` records:

- verification-project commit;
- requested and resolved Ibex revisions;
- Ibex configuration;
- simulator and compiler versions;
- simulation and analysis status;
- path, byte size, and SHA-256 for each evidence file.

## Timing interpretation

The generated Ibex instruction trace provides retirement cycles. It can prove
that a gap exists between retired instructions, but it cannot by itself prove
whether that gap came from memory, fetch, a pipeline hazard, an interrupt, or
another source.

Therefore:

- a timing analyzer exit code of `1` means an observed deviation exists;
- it does not mean an Ibex defect has been found;
- `UNKNOWN` is the expected root-cause classification when the trace lacks
  causal signals;
- Phase 1C must add waveform or simulator-internal evidence before stronger
  root-cause claims are allowed.

## Failure handling

If dependency installation, compilation, simulation, or parsing fails, the run
must stay failed. The workflow still uploads any partial logs, but it never
replaces a failed external run with synthetic passing output.
