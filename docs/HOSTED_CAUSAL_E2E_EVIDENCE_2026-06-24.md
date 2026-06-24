# Hosted Causal Waveform E2E Evidence — 2026-06-24

This record captures the hosted Phase 1C runs that join the pinned Ibex instruction trace with selected internal and interface waveform signals.

## Initial causal run

- Workflow run: `23`
- Run ID: `28098879889`
- Job ID: `83195298342`
- Pull request: `#7`
- Artifact ID: `7849664401`
- Artifact archive digest: `sha256:405c213bf70755b3184e0ba235dd9426f8025d23b875e8f04dcf008fb82f7ad6`

This run established the FST capture, signal contract, timestamp alignment, causal JSONL, and initial memory/interrupt classifications.

## Instruction-fetch scoring follow-up

- Workflow run: `30`
- Run ID: `28101955380`
- Job ID: `83206012137`
- Pull request: `#8`
- Branch head: `4c51befa947e606f066614e91ca6696e20a88147`
- Tested merge commit: `94792794546a0f433b82070bfa7a2c62cec714c1`
- Artifact ID: `7850990951`
- Artifact name: `ibex-verilator-evidence-94792794546a0f433b82070bfa7a2c62cec714c1`
- Artifact archive digest: `sha256:8bb58855a0b952c61541053d9a2ecd6b10f73df482863a486361bee5a724fa2c`

All GitHub Actions steps completed successfully: deterministic tests, dependency installation, simulator and software builds, simulation, FST capture, trace parsing, FST-to-VCD conversion, causal enrichment, timing analysis, manifest generation, and artifact upload.

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

The hosted simulator preserved `raw/sim.fst` with a size of `537363` bytes and SHA-256 `03f1c10411672d11931ecc0ce276e3811bd93836d68ecb639a4230b180188cae`.

The adapter resolved:

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

Verilator emitted `instr_req_o` and `instr_gnt_i` under one VCD identifier. The hosted adapter records the equivalent alias group and restores both aliases from the observed value.

## Retirement alignment

Both confirmed runs produced:

- rising clock snapshots: `13275`
- first/last snapshot time: `1` / `26549`
- text-trace retirement events: `1204`
- matched `rvfi_valid` retirement times: `1204`
- alignment ratio: `1.0`
- trace-to-waveform offset: `-1`

The offset is inferred deterministically over the bounded range `-4..4`; it is not hard-coded.

## Enriched timing samples

The adapter emitted `1203` timing rows and recorded:

- `461` samples with an accepted data transaction pending without `data_rvalid`;
- `443` samples with an accepted instruction transaction pending without `instr_rvalid`;
- `6` samples with `rvfi_valid && rvfi_intr`;
- `0` samples with `rvfi_valid && rvfi_trap`.

## Version 0.6.0 timing result

Against the same one-cycle retirement-gap baseline, hosted run #30 produced:

- total samples: `1203`
- on-time samples: `323`
- delayed observations: `880`
- `MEMORY_WAIT`: `385`, confidence `0.85`
- `INSTRUCTION_FETCH_WAIT`: `248`, confidence `0.75`
- `INTERRUPT_SERVICE`: `6`, confidence `0.85`
- `UNKNOWN`: `241`, confidence `0.0`

This exactly matched the offline replay prediction made before run #30. Compared with version 0.5.0, `248` previously unknown observations gained an explicit instruction-fetch wait classification, while all memory, interrupt, on-time, and total counts remained unchanged.

A fetch candidate requires a positive `instruction_wait_cycles` or `instruction_grant_wait_cycles`; `instr_req=true` alone remains insufficient. When memory or interrupt evidence overlaps, its higher confidence remains primary and fetch wait is preserved as a secondary candidate.

These counts are behavioral classifications, not defect counts. Fetch waiting may be normal instruction-memory latency or expected Simple System behavior.

## Bundle integrity

The run #30 manifest listed `39` files. Every file was independently checked after download for presence, byte size, and SHA-256. All `39/39` entries matched with no missing or modified evidence.

Key evidence files:

- `raw/sim.fst`
- `normalized/timing.jsonl`
- `normalized/timing-causal.jsonl`
- `normalized/causal-report.json`
- `normalized/timing-report.json`
- `manifest.json`

## Claim boundary

These runs prove that the pinned hosted flow can capture, align, normalize, and classify selected causal waveform evidence reproducibly. They are not formal verification, physical timing analysis, coverage closure, silicon sign-off, or proof that classified delays are processor bugs.
