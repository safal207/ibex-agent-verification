# Ibex Agent Verification

> Deterministic, agent-friendly verification scaffolding for the lowRISC Ibex RISC-V core.

[![CI](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-early%20prototype-orange.svg)](docs/ROADMAP.md)

## Why this repository exists

Hardware verification produces large traces, failing programs, waveforms, logs, and configuration details. AI coding agents can help generate tests and reduce failures, but only if the evidence path stays deterministic and reviewable.

This repository starts with two narrow capabilities:

1. compare architectural execution events with an expected trace;
2. detect cycle deviations and rank evidence-backed timing causes;
3. emit machine-readable reports and stable process exit codes;
4. keep every future AI-generated action behind reproducible artifacts.

The intended target is the **lowRISC Ibex Simple System**, which can run bare-metal binaries in a Verilator simulation and produces an instruction trace. Ibex itself is not vendored here; the bootstrap script clones the official upstream repository.

## Status — read this first

This is an **early, honest prototype**.

- The local JSONL trace comparator works and is covered by tests.
- The timing analyzer works on normalized timing samples and synthetic fixtures.
- The repository does **not** yet claim end-to-end Ibex correctness or physical timing verification.
- The Ibex text-trace adapter, waveform signal extractor, reference ISA oracle, test generation, and failure minimization are roadmap items.
- No benchmark, coverage, or bug-finding performance claim is made.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# Passing functional comparison
ibex-av compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_pass.jsonl \
  --report artifacts/pass-report.json

# Deliberate functional mismatch: exits with code 1
ibex-av compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_fail.jsonl \
  --report artifacts/fail-report.json

# Synthetic memory-wait timing anomaly: exits with code 1
ibex-av analyze-timing \
  --input examples/timing/memory_wait.jsonl \
  --report artifacts/timing-report.json
```

Or run:

```bash
make test
make demo
```

## Timing root cause analysis

The analyzer receives the expected and actual cycle count plus explicit causal signals. It reports the cycle delta, a ranked primary cause, confidence score, and the exact evidence used.

Example result:

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

Supported initial candidates include memory wait, branch recovery, pipeline hazard, bus contention, interrupt service, long-latency execution, and clock-domain waiting. If the required signals are absent, the analyzer returns `UNKNOWN` rather than inventing a cause.

Confidence is a deterministic rule score, **not** a statistical probability. See [Timing Root Cause Analysis](docs/TIMING_ANALYSIS.md).

## Repository map

```text
.
├── AGENTS.md                         # Guardrails for Codex/AI coding agents
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── TIMING_ANALYSIS.md
│   └── VERIFICATION_PROTOCOL.md
├── examples/
│   ├── timing/                       # Cycle-level timing fixtures
│   └── traces/                       # Architectural trace fixtures
├── scripts/
│   ├── bootstrap_ibex.sh             # Clone official lowRISC/ibex
│   ├── build_ibex_simple_system.sh   # Run upstream FuseSoC build commands
│   └── run_fixture_demo.sh
├── src/ibex_agent_verification/
│   ├── cli.py
│   ├── comparator.py
│   ├── models.py
│   ├── timing.py
│   └── trace_io.py
└── tests/
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

## Ibex integration path

The official Ibex Simple System contains an Ibex core, unified instruction/data memory, basic output and halt peripherals, a timer, and a software framework. Its documented Verilator flow produces `trace_core_00000000.log`.

```bash
./scripts/bootstrap_ibex.sh
./scripts/build_ibex_simple_system.sh
```

The build script validates prerequisites and then follows the upstream commands. It does not hide missing toolchain setup or silently substitute a fake simulator.

The next integration layer must preserve the raw instruction trace and waveform evidence, extract normalized architectural and cycle-level events, and record the exact Ibex revision, configuration, simulator, and compiler versions.

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
