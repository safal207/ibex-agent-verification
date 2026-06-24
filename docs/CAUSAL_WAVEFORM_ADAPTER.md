# Causal Waveform Adapter

The instruction trace proves *when* instructions retire. Phase 1C adds selected
waveform signals that can explain some of the cycles between adjacent retirement
events without inventing unsupported pipeline state.

## Pinned hosted path

The pinned Ibex Simple System target already compiles Verilator with FST tracing.
The E2E runner starts the simulator with:

```text
--trace=artifacts/ibex-e2e/raw/sim.fst
```

The raw FST is preserved as evidence. `fst2vcd` creates a temporary VCD for the
streaming extractor; the expanded VCD is deleted before manifest generation.

## Initial signal contract

The first adapter slice requires these signals from the pinned hierarchy:

- system clock: `TOP.ibex_simple_system.clk_sys`;
- retirement validity: `u_top.rvfi_valid`;
- retirement interrupt/trap flags: `u_top.rvfi_intr`, `u_top.rvfi_trap`;
- instruction request/grant/response: `instr_req_o`, `instr_gnt_i`,
  `instr_rvalid_i`;
- data request/grant/response: `data_req_o`, `data_gnt_i`, `data_rvalid_i`.

`timer_irq` is optional and is recorded when present. Required signals are
resolved by exact hierarchy suffix and must be unique. Missing or ambiguous
required signals fail the run instead of silently weakening the evidence.

## Alignment

The text trace metadata contains simulation time and retirement cycle. The VCD
adapter samples selected signals on rising clock edges and requires at least 95%
of retirement timestamps to align exactly with waveform snapshots.

For timing sample `N`, the evidence interval is:

```text
previous retirement time < waveform time <= current retirement time
```

The report records the number of retirement times, matched timestamps, alignment
ratio, resolved full signal names, and missing optional signals.

## Derived causal fields

The adapter adds only fields supported by observed handshakes:

- `data_req=true` when a data request appears in the interval;
- `memory_wait_cycles=N` while an accepted data transaction is pending without
  `data_rvalid`;
- `data_ready=false` only when such pending cycles are observed;
- `bus_wait_cycles=N` and `bus_grant=false` while a request lacks a grant;
- `instruction_wait_cycles=N` and related instruction handshake observations;
- `interrupt=true` only when `rvfi_valid && rvfi_intr` is observed;
- `rvfi_trap=true` only when `rvfi_valid && rvfi_trap` is observed;
- a waveform time-range reference for every enriched timing sample.

The existing timing analyzer consumes memory, bus, and interrupt evidence.
Instruction-fetch observations are preserved for a later dedicated cause rule.

## Evidence outputs

```text
raw/sim.fst
normalized/timing.jsonl
normalized/timing-causal.jsonl
normalized/causal-report.json
normalized/timing-report.json
```

The FST and all normalized reports are covered by the evidence manifest and
SHA-256 inventory.

## Limits

This slice does not yet claim branch misprediction, pipeline hazard, flush, or
execution-unit causes because those internal signals are not part of the initial
contract. A data handshake can explain waiting on the data interface, but it is
not physical static timing analysis and it is not silicon sign-off evidence.
