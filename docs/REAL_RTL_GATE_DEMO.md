# Real RTL Silicon Gate Demo

This experiment moves the evidence gate from generated fixtures and firmware-only
changes to an actual RTL modification in the pinned lowRISC Ibex simple system.

## Intentional RTL candidate

The baseline uses the pinned upstream source unchanged:

```systemverilog
.BExtraDelay(`INSTR_CYCLE_DELAY)
```

The candidate applies one reviewable patch:

```systemverilog
.BExtraDelay(1)
```

The changed parameter belongs to the instruction-side port of `ram_2p`. The
upstream module already implements and documents this extra delay path, so the
demo exercises a real supported RTL mechanism rather than corrupting read data
or introducing undefined bus behavior.

Patch file:

```text
examples/rtl_gate/instruction_memory_delay.patch
```

## Evidence sequence

```text
pinned Ibex commit
       ├── clean worktree ──────── build baseline simulator
       └── patched worktree ───── build candidate simulator
                                         ↓
                            identical bare-metal firmware
                                         ↓
       baseline run ───── trace + FST + timing + control-flow evidence
       candidate run A ── trace + FST + timing + control-flow evidence
       candidate run B ── trace + FST + timing + control-flow evidence
                                         ↓
       baseline vs candidate A architectural comparison → must MATCH
       candidate A vs candidate B replay comparison     → must MATCH
                                         ↓
                        deterministic Silicon Evidence Gate
                                         ↓
                              expected decision: BLOCK
```

The firmware is the existing register-only deterministic workload from:

```text
examples/firmware_gate/firmware_gate_baseline.c
```

It does not enable timer interrupts or read cycle counters. This keeps the
architectural event sequence stable while the RTL latency changes.

## Success criteria

The hosted workflow succeeds only when all of the following are true:

- the baseline and candidate simulators are built from separate worktrees;
- the candidate worktree contains exactly the intended RTL patch;
- the two simulator binaries have recorded SHA-256 digests;
- the same firmware ELF completes successfully on both variants;
- both variants print `Firmware gate result` and `00000100`;
- baseline and candidate architectural traces match exactly;
- a second candidate execution reproduces the same architectural trace;
- all three runs preserve raw FST and instruction-trace evidence;
- the gate manifest is bound to the checked-out project commit;
- the gate returns `BLOCK` with a timing or delayed-redirect regression reason.

## Run locally

External prerequisites are the same as the normal pinned Ibex E2E workflow:
Verilator, FuseSoC dependencies, GTKWave/FST tools, SRecord, and a bare-metal
RISC-V GCC toolchain.

```bash
bash scripts/run_real_rtl_gate_demo.sh
```

Default output:

```text
artifacts/real-rtl-gate-demo/
├── baseline/
│   ├── raw/
│   └── normalized/
├── candidate-a/
│   ├── raw/
│   └── normalized/
├── candidate-b/
│   ├── raw/
│   └── normalized/
├── gate/
│   ├── evidence/
│   │   ├── candidate-rtl.patch
│   │   ├── trace-comparison.json
│   │   ├── candidate-replay-comparison.json
│   │   ├── baseline-timing.json
│   │   ├── candidate-timing.json
│   │   ├── baseline-control-flow.json
│   │   ├── candidate-control-flow.json
│   │   └── manifest.json
│   ├── gate-request.json
│   └── gate-decision.json
├── build-logs/
├── simulators/
├── demo-summary.json
└── tool-versions.txt
```

## Hosted artifact

The GitHub Actions workflow uploads:

```text
real-rtl-silicon-gate-<commit-sha>
```

for 14 days. Upload uses `if: always()` so failed source checkout, patching,
building, simulation, parsing, or gating still leaves partial evidence.

## What this proves

The demonstration proves that the repository can:

1. bind an AI-attributed RTL change to an exact patch and project commit;
2. build clean and modified hardware models independently;
3. show architectural equivalence across those hardware models;
4. reproduce the candidate execution independently;
5. preserve raw waveform and trace evidence;
6. block a functionally correct candidate because measured timing evidence
   violates policy.

## Boundary

This is a controlled verification demonstration, not a claim that the upstream
Ibex design is defective. The candidate intentionally selects a slower supported
memory configuration. The result does not constitute physical timing closure,
formal proof, power analysis, coverage closure, or silicon sign-off.

A non-sequential PC still proves only an architectural redirect. It does not by
itself prove a branch misprediction or pipeline flush.
