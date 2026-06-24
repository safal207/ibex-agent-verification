# Hosted Ibex Verilator E2E Evidence — 2026-06-24

This record captures the first completed hosted GitHub Actions run of the pinned
Ibex Verilator evidence pipeline.

## Hosted run

- Workflow: `Ibex Verilator E2E`
- Run number: `17`
- Run ID: `28096034841`
- Job ID: `83185641861`
- Pull request: `#5`
- Run URL: https://github.com/safal207/ibex-agent-verification/actions/runs/28096034841
- Artifact ID: `7848473121`
- Artifact name: `ibex-verilator-evidence-fc5ac66d4d080ff04ca139e27f427a52178a3aa3`
- Artifact archive digest: `sha256:eb867a06e55bdddf532bbbe6a793ebd61dfded72fb332f256eeea70b98cb1cf2`

The workflow completed successfully. Unit tests, dependency installation, the
pinned simulator build, upstream software compilation, simulation, trace
normalization, timing analysis, manifest generation, and artifact upload all
completed with successful GitHub Actions step conclusions.

## Pinned device under test

- Repository: `lowRISC/ibex`
- Requested ref: `022f084096baed0a9b5ebdf697ed2965f13e8ed8`
- Resolved commit: `022f084096baed0a9b5ebdf697ed2965f13e8ed8`
- Configuration: `small`
- Simulator: Verilator
- Program: upstream `examples/sw/simple_system/hello_test/hello_test.elf`

## Recorded toolchain

- Python: `3.12.13`
- pip: `26.1.2`
- FuseSoC: `2.4.3`
- Verilator: `5.020`
- RISC-V GCC: `riscv64-unknown-elf-gcc 13.2.0`
- Make: `4.3`
- Git: `2.54.0`

The upstream program was compiled for `rv32imc_zicsr`. The explicit `zicsr`
extension is required by the current assembler for the CSR instructions used by
`simple_system_common.c`.

## Program and trace result

The simulated program emitted the expected output:

```text
Hello simple system
DEADBEEF
BAADF00D
Tick!
Tock!
Tick!
Tock!
Tick!
```

The parser report recorded:

- status: `PARSED`
- source lines: `1205`
- header lines: `1`
- instructions: `1204`
- first retirement cycle: `6`
- last retirement cycle: `13270`
- raw trace SHA-256: `fb84a83e007ea85615182c6e5373bf9ed16a44835fb10ea319dea726ba9d3dff`

The normalized metadata contains:

- `844` compressed 16-bit instructions;
- `360` 32-bit instructions;
- `462` instruction records associated with memory evidence.

## Evidence bundle integrity

The generated manifest contains `32` files with path, byte size, and SHA-256.
After downloading the hosted artifact, every listed file was independently
rehashed. All `32/32` entries matched both the recorded size and SHA-256; no
integrity mismatch was found.

Key preserved outputs include:

- exact replay commands;
- tool versions;
- upstream ELF;
- raw instruction trace;
- simulator stdout and stderr;
- program log and performance counters;
- architectural JSONL;
- metadata JSONL;
- timing JSONL and report;
- parser report;
- evidence manifest.

## Timing interpretation

The timing analyzer used a deliberately simple baseline of one retirement cycle
per adjacent instruction pair. It evaluated `1203` cycle gaps:

- `323` were `ON_TIME` against that baseline;
- `880` were reported as `DELAY_ANOMALY` observations;
- every one of the `880` observations had primary cause `UNKNOWN` and confidence
  `0.0` because no supported causal signal was present.

The analyzer exit code was `1`, meaning deviations were observed. It does **not**
mean that 880 processor defects were found. The text retirement trace proves
cycle gaps, but it does not prove whether a gap came from memory wait, pipeline
control, interrupts, peripherals, testbench behavior, or another source.

This result validates the evidence pipeline, not processor correctness and not a
physical timing or silicon-signoff claim.

## Next verification boundary

Phase 1C must add waveform or simulator-internal causal signals before the
project may make stronger timing root-cause claims. Candidate signals include
instruction retirement, fetch/data request and response handshakes, stalls,
flushes, branch redirects, and interrupt entry.
