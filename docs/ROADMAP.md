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
- memory, branch, pipeline, bus, interrupt, execution-unit, and clock-domain rules
- explicit `UNKNOWN` result when evidence is insufficient
- synthetic fixtures and CLI report

## Phase 1A — official Ibex text-trace adapter ✅

- parse documented `trace_core_<HARTID>.log` format
- preserve raw-input SHA-256
- extract simulation time, cycle, PC, instruction, disassembly, registers, and memory evidence
- preserve compressed versus uncompressed instruction width in metadata
- convert architectural events and cycle gaps to JSONL
- fail with source-line context on unsupported input
- fixture tests pinned to lowRISC/ibex commit `022f084096baed0a9b5ebdf697ed2965f13e8ed8`

## Phase 1B — reproducible Ibex simulator run 🧪

Implementation is present; a successful hosted GitHub Actions run is still required before this phase is marked complete.

- ✅ pin an explicit Ibex revision and configuration
- ✅ install and record Verilator, FuseSoC, RISC-V GCC, Make, Git, Python, and pip versions
- ✅ build Ibex Simple System under Verilator
- ✅ compile upstream `hello_test.elf`
- ✅ validate the real program output
- ✅ retain raw trace, counters, stdout, stderr, commands, versions, configuration, ELF, and hashes
- ✅ feed the generated trace into the Phase 1A adapter
- ✅ create a versioned evidence manifest with SHA-256 per file
- ✅ upload complete or partial evidence from GitHub Actions
- ⏳ confirm the first successful hosted run and inspect its artifact

## Phase 1C — causal timing signal adapter

- extract cycle boundaries and supported causal signals from waveform or simulator instrumentation
- map real Ibex signals into normalized timing samples
- distinguish observation (`memory_access`) from causal proof (`memory_wait_cycles`, `data_ready=false`)
- add pinned waveform fixtures and deterministic extraction tests

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
