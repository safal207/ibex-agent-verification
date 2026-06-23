# Ibex Agent Verification

> Deterministic, agent-friendly verification scaffolding for the lowRISC Ibex RISC-V core.

[![CI](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-initial%20scaffold-orange.svg)](docs/ROADMAP.md)

## Why this repository exists

Hardware verification produces large traces, failing programs, waveforms, logs, and configuration details. AI coding agents can help generate tests and reduce failures, but only if the evidence path stays deterministic and reviewable.

This repository starts with a narrow core:

1. represent architectural execution events as normalized JSONL;
2. compare a device-under-test trace with an expected trace;
3. emit a machine-readable mismatch report;
4. return stable process exit codes suitable for CI and agents;
5. keep every future AI-generated action behind reproducible artifacts.

The intended target is the **lowRISC Ibex Simple System**, which can run bare-metal binaries in a Verilator simulation and produces an instruction trace. Ibex itself is not vendored here; the bootstrap script clones the official upstream repository.

## Status — read this first

This is an **initial, honest scaffold**.

- The local JSONL trace comparator works and is covered by tests.
- The repository does **not** yet claim end-to-end Ibex correctness checking.
- The Ibex text-trace adapter, reference ISA oracle, test generation, and failure minimization are roadmap items.
- No benchmark or bug-finding performance claim is made.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# Passing comparison
ibex-av compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_pass.jsonl \
  --report artifacts/pass-report.json

# Deliberate mismatch: exits with code 1
ibex-av compare \
  --expected examples/traces/expected.jsonl \
  --actual examples/traces/actual_fail.jsonl \
  --report artifacts/fail-report.json
```

Or run:

```bash
make test
make demo
```

## Repository map

```text
.
├── AGENTS.md                         # Guardrails for Codex/AI coding agents
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   └── VERIFICATION_PROTOCOL.md
├── examples/traces/                  # Deterministic fixtures
├── scripts/
│   ├── bootstrap_ibex.sh             # Clone official lowRISC/ibex
│   ├── build_ibex_simple_system.sh   # Run upstream FuseSoC build commands
│   └── run_fixture_demo.sh
├── src/ibex_agent_verification/
│   ├── cli.py
│   ├── comparator.py
│   ├── models.py
│   └── trace_io.py
└── tests/
```

## Trace contract

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

## Verification principle

```text
agent proposal -> deterministic test artifact -> simulator/oracle runs
              -> normalized traces -> comparator -> evidence bundle
              -> human-reviewable issue or pull request
```

An agent may propose tests and explanations. It may not declare a processor bug without preserving the program, configuration, raw outputs, normalized traces, tool versions, and comparator report.

## Upstream and licensing

- Ibex upstream: https://github.com/lowRISC/ibex
- Ibex documentation: https://ibex-core.readthedocs.io/
- Ibex is licensed under Apache License 2.0 unless otherwise noted.
- This repository is also licensed under Apache License 2.0.

Ibex is a lowRISC project. This repository is independent and is not endorsed by lowRISC.
