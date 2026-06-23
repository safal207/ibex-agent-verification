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

## Phase 1 — Ibex Simple System adapters

- parse `trace_core_00000000.log`
- preserve raw simulator output
- capture Ibex commit/config/tool versions
- convert architectural events to JSONL
- extract cycle boundaries and causal signals from trace or waveform evidence
- map real Ibex signals into normalized timing samples
- fixture tests from a pinned upstream revision

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
