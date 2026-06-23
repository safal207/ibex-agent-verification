# Roadmap

## Phase 0 — deterministic local core ✅

- JSONL trace schema
- normalization of integer and hexadecimal values
- event-by-event comparison
- JSON report
- unit tests and CI

## Phase 1 — Ibex Simple System adapter

- parse `trace_core_00000000.log`
- preserve raw simulator output
- capture Ibex commit/config/tool versions
- convert architectural events to JSONL
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

## Non-goals for the initial scaffold

- claiming formal verification;
- replacing the Ibex DV environment;
- generating silicon-ready sign-off evidence;
- reporting speculative bugs upstream.
