# Timing Root Cause Analysis

The timing analyzer detects deviations from a supplied cycle baseline and ranks supported causes using explicit signals. It is deterministic: the same JSONL input produces the same report.

## Important boundary

This module analyzes **cycle-level execution deviations**. It does not perform static timing analysis, sign-off timing closure, analog clock-jitter measurement, or prove a physical silicon defect.

A reported cause is a rule-based classification supported by the listed evidence. It must not be presented as a confirmed processor defect until the relevant signals, waveform, configuration, program, and environment are reviewed.

## Input contract

One JSON object per line:

```json
{
  "step": 25,
  "cycle_start": 104,
  "cycle_end": 112,
  "expected_cycles": 2,
  "signals": {
    "pipeline_stall": true,
    "data_req": true,
    "data_ready": false,
    "memory_wait_cycles": 5
  }
}
```

The analyzer calculates:

```text
actual_cycles = cycle_end - cycle_start
delta_cycles  = actual_cycles - expected_cycles
```

Steps must increase strictly. Required cycle fields must be non-negative integers.

## Result states

- `ON_TIME`: actual cycles equal the supplied baseline.
- `FASTER_THAN_EXPECTED`: execution completed below the baseline; no cause is inferred.
- `DELAY_ANOMALY`: execution exceeded the baseline.
- `INVALID_INPUT`: malformed JSONL or invalid fields.

The top-level report is `ANOMALY_DETECTED` when any sample is not `ON_TIME`.

## Supported evidence-backed candidates

- `MEMORY_WAIT`
- `INSTRUCTION_FETCH_WAIT`
- `BRANCH_RECOVERY`
- `PIPELINE_HAZARD`
- `BUS_CONTENTION`
- `INTERRUPT_SERVICE`
- `LONG_LATENCY_EXECUTION`
- `CLOCK_DOMAIN_CROSSING`
- `UNKNOWN`

Confidence is a deterministic rule score, not a statistical probability. The report preserves every matched signal and returns ranked candidates when multiple causes are supported.

## Instruction fetch wait rule

`INSTRUCTION_FETCH_WAIT` is emitted only when at least one explicit wait counter is positive:

- `instruction_wait_cycles`: an accepted instruction transaction remains pending without `instr_rvalid`;
- `instruction_grant_wait_cycles`: an instruction request remains ungranted.

Supporting observations may increase confidence:

- `instr_req=true`;
- `instr_ready=false`;
- `instr_grant=false`.

A normal `instr_req=true` without a positive wait counter is **not** sufficient and does not create a candidate. For the common hosted response-wait evidence:

```json
{
  "instruction_wait_cycles": 3,
  "instr_req": true,
  "instr_ready": false
}
```

The deterministic confidence is `0.75`.

When the same interval contains stronger memory evidence (`0.85`) or interrupt evidence (`0.85`), those remain primary and instruction fetch wait is preserved as a secondary candidate. This prevents normal prefetch overlap from replacing a better-supported cause.

## Command

```bash
ibex-av analyze-timing \
  --input artifacts/ibex-e2e/normalized/timing-causal.jsonl \
  --report artifacts/ibex-e2e/normalized/timing-report.json
```

Exit codes:

- `0`: all samples are on time;
- `1`: at least one timing anomaly exists;
- `2`: invalid input or execution error.

## Current limits

The pinned hosted waveform adapter currently supplies memory, instruction-fetch, interrupt, and trap observations. Branch recovery, true pipeline hazards, flushes, and execution-unit waits require additional explicit Ibex signals before those candidates can be confirmed from the hosted E2E waveform.

The one-cycle retirement-gap baseline is intentionally simple. A classified wait may be expected behavior of the instruction memory, data memory, peripheral, program, or interrupt flow rather than a processor bug.
