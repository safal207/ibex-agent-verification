# Changelog

## 0.5.0 — 2026-06-24

- Confirmed the first successful hosted pinned Ibex Verilator E2E run and independently rehashed every manifest-listed file.
- Added support for the real hosted Ibex trace header spelling `Insn` in addition to the documentation spelling `Instr`.
- Added regression coverage for real hosted trace headers and memory-store rows.
- Explicitly enabled `Zicsr` when compiling upstream `hello_test` with current RISC-V GCC.
- Improved E2E diagnostics and added fast deterministic tests before the expensive simulator build.
- Added raw FST waveform capture to the pinned hosted Ibex experiment.
- Added strict VCD signal resolution for clock, RVFI, instruction handshakes, data handshakes, and timer IRQ.
- Added deterministic retirement-to-waveform offset inference with a 95% fail-closed alignment threshold.
- Added support for equivalent signal aliases that Verilator emits under one VCD identifier.
- Added causal timing enrichment for data response waits, bus grant waits, instruction response waits, interrupts, and traps.
- Added `timing-causal.jsonl`, `causal-report.json`, and raw `sim.fst` to the evidence bundle and SHA-256 manifest.
- Confirmed hosted causal run #23 with `1204/1204` aligned retirements and `39/39` independently verified manifest files.
- Classified the one-cycle-baseline delayed observations as `385 MEMORY_WAIT`, `6 INTERRUPT_SERVICE`, and `489 UNKNOWN` without treating classifications as defect claims.
- Made PR E2E runs cancel stale PR runs while preserving active `main` and manual runs.
- Marked roadmap Phase 1B complete and recorded the first successful Phase 1C hosted slice.

## 0.4.0 — 2026-06-24

- Added a pinned Ibex Simple System build and Verilator execution workflow.
- Added upstream `hello_test` compilation and output validation.
- Added complete and partial GitHub Actions evidence artifact uploads.
- Added raw simulator logs, instruction trace, performance counters, and ELF preservation.
- Added normalized architectural, metadata, and timing outputs from the real trace.
- Added an evidence manifest with project/DUT commits, tool versions, commands, byte sizes, and SHA-256 hashes.
- Added evidence-manifest tests and E2E documentation.
- Kept hosted-run success explicitly unconfirmed until GitHub Actions produces a completed artifact.

## 0.3.0 — 2026-06-24

- Added a strict parser for the official lowRISC Ibex instruction-trace format.
- Added architectural, metadata, and timing JSONL outputs.
- Added source SHA-256 reporting and source-line validation errors.
- Added support for compressed/uncompressed instruction width, register reads/writes, and memory evidence.
- Added a pinned documentation-derived fixture from lowRISC/ibex commit `022f084096baed0a9b5ebdf697ed2965f13e8ed8`.
- Added CLI, demo integration, tests, and adapter documentation.
- Preserved the distinction between observed memory access and proven memory wait.

## 0.2.0 — 2026-06-24

- Added deterministic timing-sample JSONL contract.
- Added cycle deviation detection and evidence-backed root cause ranking.
- Added initial rules for memory wait, branch recovery, pipeline hazard, bus contention, interrupts, long-latency execution, and clock-domain waiting.
- Added explicit `UNKNOWN` classification when causal evidence is insufficient.
- Added timing CLI, synthetic fixture, tests, reports, and documentation.

## 0.1.0 — 2026-06-24

- Added deterministic JSONL trace contract.
- Added event comparator and machine-readable reports.
- Added fixture tests, GitHub Actions CI, and Codex guardrails.
- Added honest Ibex Simple System bootstrap/build scaffolding.
