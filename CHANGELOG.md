# Changelog

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
