# Real Firmware Silicon Gate Demo

This workflow replaces the generated `BLOCK` fixture with a hardware-backed
Ibex experiment.

It builds one pinned Verilator simulator and two bare-metal firmware variants:

- `firmware_gate_baseline.c`: performs 256 register-only increments;
- `firmware_gate_candidate.c`: produces the same visible result but performs
  additional volatile memory reads.

Both programs print the same result (`0x00000100`) and return success.

## Evidence sequence

```text
pinned lowRISC/ibex revision
          ↓
one Verilator simulator build
          ↓
baseline firmware run
          ↓
candidate firmware run A ─┐
                          ├─ architectural comparator → MATCH
candidate firmware run B ─┘
          ↓
baseline/candidate FST + instruction traces
          ↓
causal timing reports + branch redirect reports
          ↓
Silicon Evidence Gate → expected BLOCK
```

The candidate is run twice so functional determinism is checked independently
from the baseline performance comparison. The gate does not receive a deliberate
baseline-versus-candidate architectural mismatch. Its comparator input is the
candidate oracle/replay pair, which must be `MATCH`.

## Why the candidate should be blocked

The candidate preserves the final firmware result but adds real volatile memory
traffic. The pinned Ibex simulator and waveform adapter determine whether that
change introduces additional explained timing anomalies, unexplained timing
anomalies, or delayed branch redirects.

The gate policy allows no new anomalies:

```json
{
  "max_new_explained_timing_anomalies": 0,
  "max_new_delayed_redirects": 0
}
```

The hosted workflow succeeds only when:

- both firmware binaries build and run successfully;
- both print the expected result;
- candidate A and candidate B architectural traces match exactly;
- the evidence manifest is bound to the checked-out project commit;
- the gate returns `BLOCK` with a timing or redirect regression reason.

## Run locally

The external prerequisites are the same as the pinned Ibex E2E workflow:
Verilator, FuseSoC dependencies, GTKWave/FST tools, SRecord, and a bare-metal
RISC-V GCC toolchain.

```bash
bash scripts/run_real_firmware_gate_demo.sh
```

The default output is:

```text
artifacts/real-firmware-gate-demo/
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
│   ├── gate-request.json
│   └── gate-decision.json
├── build-logs/
├── demo-summary.json
└── tool-versions.txt
```

Every run preserves:

- firmware source and ELF;
- disassembly;
- raw Ibex instruction trace;
- raw FST waveform;
- simulator log and performance counters;
- normalized architectural and timing evidence;
- causal timing and control-flow reports.

## Hosted artifact

The workflow uploads:

```text
real-firmware-silicon-gate-<commit-sha>
```

for 14 days. Upload uses `if: always()` so a failed build, simulation, parser,
or gate still leaves partial evidence for inspection.

## Causal boundary

This demonstrates a real firmware performance gate on a pinned RTL simulator.
It does not claim:

- a defect in Ibex;
- silicon timing closure or tape-out sign-off;
- that all memory traffic is undesirable;
- that an architectural redirect proves a pipeline flush;
- that this single microbenchmark represents production LLM inference silicon.

The intentional regression is in the candidate firmware workload. The value of
the demonstration is the evidence path: a functionally deterministic change is
blocked because the real simulator produces a policy-relevant timing regression.
