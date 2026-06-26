# Roadmap

## Phase 0 — deterministic local core ✅

- JSONL architectural trace schema
- normalization of integer and hexadecimal values
- event-by-event comparison
- machine-readable reports
- unit tests and CI

## Phase 0.5 — timing root cause prototype ✅

- cycle-baseline deviation detection
- deterministic evidence scoring
- ranked cause candidates
- memory, instruction-fetch, branch, pipeline, bus, interrupt, execution-unit, and clock-domain rules
- explicit `UNKNOWN` result when evidence is insufficient
- synthetic fixtures and CLI report

## Phase 1A — official Ibex text-trace adapter ✅

- parse documented and real hosted `trace_core_<HARTID>.log` headers
- preserve raw-input SHA-256
- extract simulation time, cycle, PC, instruction, disassembly, registers, and memory evidence
- preserve compressed versus uncompressed instruction width in metadata
- convert architectural events and cycle gaps to JSONL
- fail with source-line context on unsupported input
- fixture tests pinned to lowRISC/ibex commit `022f084096baed0a9b5ebdf697ed2965f13e8ed8`

## Phase 1B — reproducible Ibex simulator run ✅

- ✅ pin an explicit Ibex revision and configuration
- ✅ build Ibex Simple System and upstream `hello_test` under Verilator
- ✅ validate real program output
- ✅ preserve raw trace, counters, stdout, stderr, commands, versions, configuration, ELF, and hashes
- ✅ generate normalized evidence and a SHA-256 manifest
- ✅ confirm hosted runs and independently rehash manifest-listed files
- ✅ provide a fail-closed manifest verifier and run it before artifact upload

See [Hosted Ibex Verilator E2E Evidence](HOSTED_E2E_EVIDENCE_2026-06-24.md) and [Evidence Bundle Verification](EVIDENCE_BUNDLE_VERIFICATION.md).

## Phase 1C — causal timing signal adapter 🧪

Hosted run #30 aligned all `1204/1204` retirements, preserved the same pinned raw evidence, and classified delayed observations as `385 MEMORY_WAIT`, `248 INSTRUCTION_FETCH_WAIT`, `6 INTERRUPT_SERVICE`, and `241 UNKNOWN`.

- ✅ strict pinned hierarchy contract for clock, RVFI, instruction, and data handshakes
- ✅ streaming VCD parsing with fail-closed signal resolution
- ✅ waveform/trace timestamp alignment and recorded offset
- ✅ equivalent aliases for shared Verilator VCD identifiers
- ✅ data wait, grant wait, instruction wait, interrupt, and trap observations
- ✅ raw FST plus normalized causal JSONL and reports
- ✅ hosted artifact integrity verification
- ✅ dedicated `INSTRUCTION_FETCH_WAIT` scoring requiring an explicit wait counter
- ✅ hosted confirmation: `248` fetch waits promoted from `UNKNOWN`
- ⏳ branch redirect and pipeline flush signals
- ⏳ true pipeline-hazard and execution-unit signals
- ⏳ compact pinned real-waveform regression slices

See [Causal Waveform Adapter](CAUSAL_WAVEFORM_ADAPTER.md) and [Hosted Causal Waveform E2E Evidence](HOSTED_CAUSAL_E2E_EVIDENCE_2026-06-24.md).

## Phase 2 — reference ISA oracle

- add a pinned Spike or Sail adapter
- align reset vector and memory map
- compare committed architectural state
- document expected differences and unsupported CSRs

## Phase 3 — generated programs

- deterministic instruction-sequence generator
- constrained memory and branch scenarios
- seed manifest and replay command
- invalid-program rejection

## Phase 4 — reducer

- minimize a failing program while preserving the mismatch
- retain original and reduced evidence bundles
- prevent nondeterministic reductions from being accepted

## Phase 5 — agent loop

- agent proposes tests, classifications, and candidate reductions
- deterministic tools execute all claims
- human reviews evidence before upstream reporting

## Future timing work

- compare timing distributions across repeated deterministic runs
- correlate waveform transitions with cycle anomalies
- distinguish DUT delay from simulator/testbench overhead
- detect recurring delay signatures across test suites
- produce causal graphs with raw-signal references

## Non-goals for the early prototype

- claiming formal verification;
- replacing the Ibex DV environment;
- performing physical static timing analysis or sign-off timing closure;
- generating silicon-ready sign-off evidence;
- reporting speculative bugs or confirmed root causes without raw evidence.
