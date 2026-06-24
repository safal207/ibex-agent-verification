# Hosted Causal Waveform E2E Evidence — 2026-06-24

This record captures the first successful hosted Phase 1C run that joins the
pinned Ibex instruction trace with selected internal and interface waveform
signals.

## Hosted run

- Workflow: `Ibex Verilator E2E`
- Run number: `23`
- Run ID: `28098879889`
- Job ID: `83195298342`
- Pull request: `#7`
- Run URL: https://github.com/safal207/ibex-agent-verification/actions/runs/28098879889
- Branch head: `aae7adc3762e8d5cc9c2d94609c6451a981ce59d`
- Tested merge commit: `84e16dbf8a0c2350591964bb7d57233e7de65ccc`
- Artifact ID: `7849664401`
- Artifact name: `ibex-verilator-evidence-84e16dbf8a0c2350591964bb7d57233e7de65ccc`
- Artifact archive digest: `sha256:405c213bf70755b3184e0ba235dd9426f8025d23b875e8f04dcf008fb82f7ad6`

All GitHub Actions steps completed successfully: deterministic tests, dependency
installation, simulator and software builds, simulation, FST capture, trace
parsing, FST-to-VCD conversion, causal enrichment, timing analysis, manifest
generation, and artifact upload.

## Pinned device and tools

- Ibex requested and resolved commit: `022f084096baed0a9b5ebdf697ed2965f13e8ed8`
- Ibex configuration: `small`
- Program: upstream `hello_test.elf`
- Python: `3.12.13`
- FuseSoC: `2.4.3`
- Verilator: `5.020`
- RISC-V GCC: `13.2.0`
- architecture: `rv32imc_zicsr`
- `fst2vcd`: `/usr/bin/fst2vcd`

## Waveform evidence

The hosted simulator preserved `raw/sim.fst` with a size of `537363` bytes.
The expanded VCD was used only as temporary processing data and was not retained
in the final bundle.

The adapter resolved these exact one-bit signals:

- `TOP.ibex_simple_system.clk_sys`
- `TOP.ibex_simple_system.u_top.rvfi_valid`
- `TOP.ibex_simple_system.u_top.rvfi_intr`
- `TOP.ibex_simple_system.u_top.rvfi_trap`
- `TOP.ibex_simple_system.u_top.instr_req_o`
- `TOP.ibex_simple_system.u_top.instr_gnt_i`
- `TOP.ibex_simple_system.u_top.instr_rvalid_i`
- `TOP.ibex_simple_system.u_top.data_req_o`
- `TOP.ibex_simple_system.u_top.data_gnt_i`
- `TOP.ibex_simple_system.u_top.data_rvalid_i`
- `TOP.ibex_simple_system.timer_irq`

Verilator emitted `instr_req_o` and `instr_gnt_i` under the same VCD identifier,
which is consistent with their equivalent wiring in this Simple System target.
The hosted adapter records the equivalent alias group and restores both aliases
from the single observed value.

## Retirement alignment

- rising clock snapshots: `13275`
- first/last snapshot time: `1` / `26549`
- text-trace retirement events: `1204`
- matched `rvfi_valid` retirement times: `1204`
- alignment ratio: `1.0`
- constant trace-to-waveform offset: `-1`

The offset means that a text-trace timestamp such as `20` corresponds to the
`rvfi_valid` rising-edge snapshot at waveform time `19`. The offset was inferred
deterministically by scoring the bounded range `-4..4`; it was not hard-coded.

## Enriched timing samples

The adapter emitted `1203` `timing-causal.jsonl` rows and recorded:

- `461` samples containing an accepted data transaction pending without
  `data_rvalid`;
- `443` samples containing an accepted instruction transaction pending without
  `instr_rvalid`;
- `6` samples containing `rvfi_valid && rvfi_intr`;
- `0` samples containing `rvfi_valid && rvfi_trap`.

Each timing row includes the original text-trace times, inferred waveform offset,
waveform interval boundaries, snapshot count, and source reference
`raw/sim.fst`.

## Timing analyzer result

The same one-cycle retirement-gap baseline produced:

- total samples: `1203`
- on-time samples: `323`
- delayed observations: `880`
- `MEMORY_WAIT`: `385`, confidence `0.85`
- `INTERRUPT_SERVICE`: `6`, confidence `0.85`
- `UNKNOWN`: `489`, confidence `0.0`

Example memory evidence contains:

```text
memory_wait_cycles=1
data_req=true
data_ready=false
```

Example interrupt evidence contains:

```text
interrupt=true
```

The causal adapter reduced the unexplained delayed observations from `880` to
`489`. This does **not** establish 391 processor defects. It classifies observed
retirement gaps using the supported waveform contract. The one-cycle baseline is
still intentionally simple, and a classified wait may be expected behavior of
the program, memory system, peripheral, or interrupt flow.

Instruction wait observations are preserved but are not yet assigned a primary
cause by the timing analyzer. Branch recovery, pipeline hazards, flushes, and
execution-unit causes remain unsupported until their own signals and rules are
added.

## Bundle integrity

The manifest listed `39` files. After downloading the artifact, every listed
file was independently checked for byte size and SHA-256. All `39/39` entries
matched; no missing or modified evidence was found.

Key additions compared with Phase 1B are:

- `raw/sim.fst`
- `normalized/timing-causal.jsonl`
- `normalized/causal-report.json`
- causal `normalized/timing-report.json`

## Claim boundary

This run proves that the pinned hosted flow can capture, align, normalize, and
use selected causal waveform evidence reproducibly. It is not formal
verification, physical timing analysis, coverage closure, silicon sign-off, or a
claim that the classified delays are bugs.
