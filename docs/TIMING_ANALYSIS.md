# Timing Root Cause Analysis

The timing analyzer detects deviations from a supplied cycle baseline and ranks supported causes using explicit signals. It is deterministic: the same JSONL input produces the same report.

## Important boundary

This module analyzes **cycle-level execution deviations**. It does not perform static timing analysis, sign-off timing closure, analog clock-jitter measurement, or prove a physical silicon defect.

A reported cause is a rule-based hypothesis supported by the listed evidence. It must not be presented as a confirmed root cause until the relevant signals, waveform, configuration, and environment are reviewed.

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
- `FASTER_THAN_EXPECTED`: execution completed below the baseline; no cause is inferred in the initial version.
- `DELAY_ANOMALY`: execution exceeded the baseline.
- `INVALID_INPUT`: malformed JSONL or invalid fields.

The top-level report is `ANOMALY_DETECTED` when any sample is not `ON_TIME`.

## Supported evidence-backed candidates

- `MEMORY_WAIT`
- `BRANCH_RECOVERY`
- `PIPELINE_HAZARD`
- `BUS_CONTENTION`
- `INTERRUPT_SERVICE`
- `LONG_LATENCY_EXECUTION`
- `CLOCK_DOMAIN_CROSSING`
- `UNKNOWN`

Confidence is a deterministic rule score, not a statistical probability. The report preserves every matched signal and returns ranked candidates when multiple causes are supported.

## Command

```bash
ibex-av analyze-timing \
  --input examples/timing/memory_wait.jsonl \
  --report artifacts/timing-report.json
```

Exit codes:

- `0`: all samples are on time;
- `1`: at least one timing anomaly exists;
- `2`: invalid input or execution error.

## Current limitation

The example fixture is synthetic. Real Ibex integration still requires an adapter that extracts cycle boundaries and causal signals from simulator traces or waveforms while preserving the raw evidence.
