# Ibex Agent Verification

> Deterministic, agent-friendly verification scaffolding for the lowRISC Ibex RISC-V core.

[![CI](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml)
[![Ibex Verilator E2E](https://github.com/safal207/ibex-agent-verification/actions/workflows/ibex-e2e.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/ibex-e2e.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-early%20prototype-orange.svg)](docs/ROADMAP.md)

## Why this repository exists

Hardware verification produces large traces, failing programs, waveforms, logs, and configuration details. AI coding agents can help generate tests and reduce failures, but only if the evidence path stays deterministic and reviewable.

This repository currently provides four narrow capabilities:

1. run a pinned Ibex Simple System experiment under Verilator;
2. parse the official human-readable Ibex instruction trace into normalized evidence;
3. compare architectural execution events with an expected trace;
4. detect cycle deviations and rank evidence-backed timing causes;
5. emit machine-readable reports and reproducible evidence bundles;
6. keep every future AI-generated action behind deterministic artifacts.

## Status — read this first

This is an **early, honest prototype**.

- The architectural JSONL comparator works and is covered by tests.
- The timing analyzer works on normalized timing samples.
- The official Ibex text-trace adapter is tested against a pinned example from lowRISC documentation.
- A pinned Verilator E2E workflow now builds and runs upstream `hello_test` and preserves raw and normalized evidence.
- The first successful hosted E2E run must still be confirmed by GitHub Actions; adding the workflow is not itself proof that the external toolchain completed.
- Waveform signal extraction, a reference ISA oracle, generated programs, and failure minimization remain roadmap items.
- No benchmark, coverage, silicon-signoff, or bug-finding performance claim is made.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# Parse an official-format Ibex instruction trace
ibex-av parse-ibex-trace \
  --input tests/fixtures/ibex_tracer/official_sample_022f0840.log \
  --output artifacts/ibex-architectural.jsonl \
  --metadata-output artifacts/ibex-metadata.jsonl \
  --timing-output artifacts/ibex-timing.jsonl \
  --report artifacts/ibex-parser-report.json

# Analyze cycle gaps derived from the Ibex trace
ibex-av analyze-timing \
  --input artifacts/ibex-timing.jsonl \
  --report artifacts/ibex-timing-report.json

# Passing functional comparison
ibex-av compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_pass.jsonl \
  --report artifacts/pass-report.json
```

Run local deterministic tests and fixtures:

```bash
make test
make demo
```

Run the real pinned Ibex experiment after installing the external prerequisites:

```bash
./scripts/run_ibex_e2e.sh
```

## Pinned Verilator E2E experiment

The E2E workflow follows the upstream Ibex Simple System sequence:

```text
pinned lowRISC/ibex commit
        ↓
FuseSoC builds Vibex_simple_system
        ↓
RISC-V GCC builds hello_test.elf
        ↓
Verilator runs the program
        ↓
raw trace + counters + logs
        ↓
normalized JSONL + timing report
        ↓
manifest with commands, versions, and SHA-256
```

Default device-under-test revision:

```text
022f084096baed0a9b5ebdf697ed2965f13e8ed8
```

The GitHub Actions job uploads `artifacts/ibex-e2e/` even when a later step fails, so build or simulator failures remain inspectable. A successful bundle requires a real simulator exit, the expected `Hello simple system` output, a non-empty instruction trace, parser success, and a completed manifest.

See [Pinned Ibex Verilator E2E Run](docs/IBEX_VERILATOR_E2E.md).

## Official Ibex trace adapter

The lowRISC tracer emits simulation time, cycle, PC, machine instruction, decoded instruction, register accesses, and memory values. The adapter converts that text into three reviewable streams:

```text
trace_core_00000000.log
        ├── architectural.jsonl  -> functional comparator
        ├── metadata.jsonl       -> cycles, width, disassembly, reads
        └── timing.jsonl         -> cycle-gap analyzer
```

The parser also reports the SHA-256 of the raw input so generated evidence can be tied back to the exact source log.

A text trace can show that instructions retired three cycles apart. It cannot necessarily prove why. A memory instruction plus a cycle gap is therefore marked as a memory association only; without explicit wait signals the timing analyzer returns `UNKNOWN`, not `MEMORY_WAIT`.

See [Official Ibex Instruction Trace Adapter](docs/IBEX_TRACE_ADAPTER.md).

## Timing root cause analysis

The analyzer receives the expected and actual cycle count plus explicit causal signals. It reports the cycle delta, a ranked primary cause, confidence score, and exact evidence used.

Example with sufficient causal evidence:

```json
{
  "status": "DELAY_ANOMALY",
  "expected_cycles": 2,
  "actual_cycles": 8,
  "delta_cycles": 6,
  "primary_cause": "MEMORY_WAIT",
  "confidence": 0.95,
  "evidence": [
    "memory_wait_cycles=5",
    "data_req=true",
    "data_ready=false",
    "pipeline_stall=true"
  ]
}
```

Supported initial candidates include memory wait, branch recovery, pipeline hazard, bus contention, interrupt service, long-latency execution, and clock-domain waiting. If required signals are absent, the analyzer returns `UNKNOWN` rather than inventing a cause.

Confidence is a deterministic rule score, **not** a statistical probability. See [Timing Root Cause Analysis](docs/TIMING_ANALYSIS.md).

## Repository map

```text
.
├── .github/workflows/
│   ├── ci.yml
│   └── ibex-e2e.yml
├── AGENTS.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IBEX_TRACE_ADAPTER.md
│   ├── IBEX_VERILATOR_E2E.md
│   ├── ROADMAP.md
│   ├── TIMING_ANALYSIS.md
│   └── VERIFICATION_PROTOCOL.md
├── examples/
│   ├── timing/
│   └── traces/
├── scripts/
│   ├── bootstrap_ibex.sh
│   ├── build_ibex_simple_system.sh
│   ├── run_fixture_demo.sh
│   └── run_ibex_e2e.sh
├── src/ibex_agent_verification/
│   ├── cli.py
│   ├── comparator.py
│   ├── evidence.py
│   ├── ibex_trace.py
│   ├── models.py
│   ├── timing.py
│   └── trace_io.py
└── tests/
    └── fixtures/ibex_tracer/
```

## Architectural trace contract

One JSON object per line:

```json
{
  "step": 0,
  "pc": "0x00100080",
  "instruction": "0x00500093",
  "register_write": {"name": "x1", "value": "0x00000005"},
  "memory": null,
  "trap": null
}
```

Hex strings and integers are accepted for numeric fields and normalized before comparison.

## Verification principle

```text
agent proposal -> deterministic test artifact -> simulator/oracle runs
              -> raw evidence -> normalized traces/timing samples
              -> comparator and cause analyzer -> evidence bundle
              -> human-reviewable issue or pull request
```

An agent may propose tests and explanations. It may not declare a processor bug or confirmed timing root cause without preserving the program, configuration, raw outputs, normalized evidence, tool versions, and deterministic report.

## Upstream and licensing

- Ibex upstream: https://github.com/lowRISC/ibex
- Ibex documentation: https://ibex-core.readthedocs.io/
- Ibex is licensed under Apache License 2.0 unless otherwise noted.
- This repository is also licensed under Apache License 2.0.

Ibex is a lowRISC project. This repository is independent and is not endorsed by lowRISC.
