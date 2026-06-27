# Ibex Agent Verification

> Deterministic, tamper-evident evidence for pinned silicon experiments, hosted inference runs, AI QA release decisions, and agent state transitions.

[![CI](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/ci.yml)
[![Ibex Verilator E2E](https://github.com/safal207/ibex-agent-verification/actions/workflows/ibex-e2e.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/ibex-e2e.yml)
[![Cerebras Live Evidence](https://github.com/safal207/ibex-agent-verification/actions/workflows/cerebras-live-evidence.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/cerebras-live-evidence.yml)
[![ProofQA Release Gate](https://github.com/safal207/ibex-agent-verification/actions/workflows/proofqa-action.yml/badge.svg)](https://github.com/safal207/ibex-agent-verification/actions/workflows/proofqa-action.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## Evidence-first verification

```text
Ibex RTL + firmware                     hosted inference request
        ↓                                         ↓
trace + waveform + versions             timestamped stream + usage
        ↓                                         ↓
normalized reports + causal analysis     deterministic timing + QA scoring
        └────────────────┬────────────────────────┘
                         ↓
             manifest + SHA-256 inventory
                         ↓
            independent bundle verification
                         ↓
       checksum + provenance + keyless attestation
                         ↓
      ProofQA quality / reliability / time policy
                         ↓
  transition policy across time, intention, and space
                         ↓
             PASS / WARN / BLOCK
```

The project preserves exact inputs, observed outputs, versions, timing evidence, hashes, transition evidence, and release-policy decisions. A simulator, agent, provider, benchmark, release asset, or release publisher is not trusted without reviewable evidence.

## Confirmed hosted evidence

| Rail | Confirmed result | Record |
|---|---|---|
| Ibex causal waveform | `1204/1204` retirements aligned; `385 MEMORY_WAIT`, `248 INSTRUCTION_FETCH_WAIT`, `6 INTERRUPT_SERVICE`, `241 UNKNOWN` | [Ibex hosted evidence](docs/HOSTED_CAUSAL_E2E_EVIDENCE_2026-06-24.md) |
| Cerebras hosted inference | `HTTP 200`, `COMPLETE`, TTFT `203.354406 ms`, provider-timed throughput `1912.297310144391 tokens/s`, SDK `1.67.0` | [Cerebras hosted evidence](docs/HOSTED_CEREBRAS_EVIDENCE_2026-06-26.md) |

The Cerebras value records one client-observed API stream. It is not a vendor-wide benchmark and makes no claim about internal WSE or RTL correctness.

## Capabilities

### Shared evidence core

- deterministic reports and exit codes;
- manifest inventories with byte sizes and SHA-256;
- fail-closed rejection of malformed paths, symlinks, missing files, modified files, and unlisted additions;
- independent verification with `ibex-av verify-evidence`;
- commit-bound GitHub Actions artifacts and release evidence;
- deterministic release ZIPs with checksum and provenance sidecars;
- byte-for-byte verification after GitHub Release download;
- OIDC-backed keyless Sigstore attestations bound to repository workflow identity.

### Silicon rail

- pinned lowRISC Ibex Simple System builds under Verilator;
- official Ibex trace parsing into architectural, metadata, and timing JSONL;
- raw FST waveform preservation;
- RVFI and interface-handshake alignment;
- architectural comparison and evidence-backed timing-cause ranking;
- reusable `ALLOW`, `BLOCK`, and `ESCALATE` gate decisions.

### Hosted inference and AI QA rail

- provider-neutral OpenAI-compatible capture format;
- monotonic timestamp and terminal-event validation;
- recursive secret-field rejection;
- real Cerebras streaming runner with fixed endpoint, disabled retries, disabled TCP warming, and safe response-header allowlisting;
- TTFT and total client-observed duration;
- provider-timed throughput when trustworthy completion timing exists;
- verified `REQUEST_FAILED` evidence for API, network, and stream failures;
- versioned core and mobile QA suites with deterministic field-level scoring;
- scorecard v3 separating end-to-end result, correctness, completion, provider reliability, and time;
- ProofQA composite action producing `PASS`, `WARN`, or `BLOCK` from configurable policies.

### Transition phase rail

- explicit `t− → t0 → t+` chronology;
- intention declaration before commitment;
- concrete action, expected result, and stopping condition at commit;
- origin, crossed boundary, destination, and destination observation;
- fail-closed rejection of backward chronology and execution before commitment;
- `IN_PROGRESS`, `VERIFIED`, or `RECALIBRATE` outcomes;
- ProofQA policies `ignore`, `warn`, and `require-verified` for gradual or strict continuation control;
- structural rejection of forged `VERIFIED` reports whose phase, issues, or axes do not converge.

## Status

This is an early, honest prototype.

- The first hosted Ibex E2E and causal-waveform runs completed on 2026-06-24.
- The first fully green Cerebras live-evidence run completed on 2026-06-26 in [Actions run 28255376630](https://github.com/safal207/ibex-agent-verification/actions/runs/28255376630).
- Release `v0.8.0` preserves that inference evidence as a deterministic release asset.
- Release `v0.8.1` reuses those immutable bytes to exercise checksum, provenance, post-download verification, and keyless attestation end to end.
- AI QA scorecard v3 includes independent correctness, completion, provider, and time diagnostics.
- Transition Phase Contract v1 verifies movement across time, intention, and space.
- ProofQA Release Gate v4 can require a structurally consistent `VERIFIED` transition before deployment or autonomous continuation.
- A dedicated immutable Marketplace action remains future work.
- No coverage-closure, silicon-signoff, provider-hardware, energy-efficiency, general model-quality, stable-latency, or vendor-wide performance claim is made.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
make test
make demo
```

Verify the committed Cerebras milestone:

```bash
ibex-av verify-evidence \
  --manifest docs/evidence/releases/v0.8.0/cerebras-live/bundle/manifest.json \
  --report /tmp/cerebras-live-verification.json
```

Verify a declared transition:

```bash
ibex-av verify-transition-phase \
  --record examples/transition-phase/payment-recovery-verified.json \
  --report /tmp/payment-recovery-transition-report.json
```

Require both model evidence and a verified transition:

```yaml
- uses: safal207/ibex-agent-verification/proofqa@<full-commit-sha>
  with:
    summary-path: artifacts/qa-benchmark/summary.json
    transition-report-path: artifacts/release-transition-report.json
    transition-policy: require-verified
    min-answer-correctness: "95"
    min-completion-reliability: "95"
    min-provider-reliability: "99"
    max-p95-duration-ms: "2000"
    fail-on: block
```

Run the pinned Ibex experiment after installing its external prerequisites:

```bash
bash ./scripts/run_ibex_e2e.sh
```

For a live hosted inference run, install the optional SDK and follow [the Cerebras runner guide](docs/CEREBRAS_CLOUD_RUNNER.md). Credentials belong in an environment variable or repository secret, never in request JSON, command arguments, logs, or evidence.

## Evidence contracts

A hosted inference capture starts with `request_start`, records optional safe headers and ordered chunks, and ends with exactly one `request_end` or `request_error`. Timestamps use a monotonic clock and may not move backward.

A successful inference bundle contains:

```text
manifest.json
analysis.json
raw/request.json
raw/capture.jsonl
```

For reasoning-model streams, the analyzer prefers provider-reported `completion_time`. If reasoning tokens exist without provider completion timing, it refuses to publish a misleading throughput value.

The pinned silicon workflow preserves raw traces, FST waveforms, normalized architectural and causal reports, tool versions, commands, manifests, and verification reports.

A transition record preserves explicit chronology, intention, spatial boundary, destination, verification booleans, and opaque evidence references. ProofQA validates the transition report's internal contract and binds its bytes by SHA-256; verification of the referenced external evidence remains a separate manifest responsibility.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Evidence Bundle Verification](docs/EVIDENCE_BUNDLE_VERIFICATION.md)
- [Release Artifact Attestations](docs/RELEASE_ATTESTATIONS.md)
- [AI QA Engineer Verification Suites](docs/AI_QA_ENGINEER_SUITE.md)
- [Mobile QA Engineer Suite](docs/MOBILE_QA_SUITE.md)
- [ProofQA GitHub Action](docs/PROOFQA_GITHUB_ACTION.md)
- [Transition Phase Contract](docs/TRANSITION_PHASE_CONTRACT.md)
- [Causal Waveform Adapter](docs/CAUSAL_WAVEFORM_ADAPTER.md)
- [Timing Root Cause Analysis](docs/TIMING_ANALYSIS.md)
- [Cerebras Cloud Runner](docs/CEREBRAS_CLOUD_RUNNER.md)
- [Inference Evidence Adapter](docs/INFERENCE_EVIDENCE.md)
- [Hosted Cerebras Evidence](docs/HOSTED_CEREBRAS_EVIDENCE_2026-06-26.md)
- [Roadmap](docs/ROADMAP.md)

## Verification principle

```text
agent or human proposal
        ↓
explicit intention and concrete commitment
        ↓
deterministic workload and configuration
        ↓
real simulator, oracle, or hosted endpoint
        ↓
raw outputs + normalized evidence + versions
        ↓
manifest + hashes + independent verification
        ↓
release checksum + provenance + keyless signature
        ↓
quality, reliability, and time policy
        ↓
transition verification across t− / t0 / t+
        ↓
human-reviewable continuation, recalibration, or block
```

An agent may propose tests and explanations. It may not declare a processor bug, confirmed timing root cause, completed state transition, presence in a destination, hardware property, or provider-wide performance result without preserving the evidence needed to audit that statement.
