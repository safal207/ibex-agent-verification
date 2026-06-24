# Causal Waveform Adapter

The instruction trace proves *when* instructions retire. Phase 1C adds selected
waveform signals that can explain some of the cycles between adjacent retirement
events without inventing unsupported pipeline state.

The first hosted causal run completed successfully on 2026-06-24. Its exact run,
artifact digest, alignment, signal paths, classifications, and integrity checks
are recorded in
[Hosted Causal Waveform E2E Evidence](HOSTED_CAUSAL_E2E_EVIDENCE_2026-06-24.md).

## Pinned hosted path

The pinned Ibex Simple System target already compiles Verilator with FST tracing.
The E2E runner starts the simulator with:

```text
--trace=artifacts/ibex-e2e/raw/sim.fst
```

The raw FST is preserved as evidence. `fst2vcd` writes an expanded temporary VCD
to standard output; the runner redirects it into the work directory for the
streaming extractor and deletes it before manifest generation.

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

Verilator may emit equivalent nets under a single VCD identifier. The hosted run
showed this for `instr_req_o` and `instr_gnt_i`. The adapter records equivalent
alias groups and restores each alias from the single observed value before
computing pending transactions.

## Alignment

The text trace metadata contains simulation time and retirement cycle. The VCD
adapter samples selected signals on rising clock edges and requires at least 95%
of retirement timestamps to align with waveform snapshots where `rvfi_valid=1`.

A constant timestamp offset is inferred deterministically over the bounded range
`-4..4`. It is selected by maximum exact `rvfi_valid` matches, recorded in the
report, and applied to every interval. The hosted run inferred `-1` and matched
all `1204/1204` retirements.

For timing sample `N`, the waveform evidence interval is:

```text
previous aligned retirement time < waveform time <= current aligned retirement time
```

The report records the number of retirement times, matched timestamps, alignment
ratio, inferred offset, resolved full signal names, equivalent alias groups, and
missing optional signals.

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
- original trace times, aligned waveform times, offset, snapshot count, and raw
  waveform source for every enriched timing sample.

The existing timing analyzer consumes memory, bus, and interrupt evidence.
Instruction-fetch observations are preserved for a later dedicated cause rule.

## Hosted result

The first hosted causal artifact contained:

- `13275` rising-edge snapshots;
- `1203` enriched adjacent-retirement samples;
- `461` samples with data response waiting;
- `443` samples with instruction response waiting;
- `6` samples with RVFI interrupt entry;
- `0` RVFI trap samples.

Against the simple one-cycle baseline, the analyzer classified delayed
observations as `385 MEMORY_WAIT`, `6 INTERRUPT_SERVICE`, and `489 UNKNOWN`.
These are evidence-backed behavioral classifications, not defect counts.

## Evidence outputs

```text
raw/sim.fst
normalized/timing.jsonl
normalized/timing-causal.jsonl
normalized/causal-report.json
normalized/timing-report.json
```

The FST and all normalized reports are covered by the evidence manifest and
SHA-256 inventory. The first hosted causal bundle contained `39` manifest-listed
files, all independently rehashed without mismatch.

## Limits

This slice does not yet claim branch misprediction, pipeline hazard, flush, or
execution-unit causes because those internal signals are not part of the initial
contract. A data handshake can explain waiting on the data interface, but it is
not physical static timing analysis and it is not silicon sign-off evidence.
