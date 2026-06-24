# Silicon Evidence Gate

The silicon evidence gate turns reproducible verification outputs into one
machine-readable decision for an AI-generated RTL, firmware, constraint, or
testbench change:

- `ALLOW`: required evidence is commit-bound and no configured regression exists;
- `BLOCK`: a hard safety or correctness condition failed;
- `ESCALATE`: evidence is valid, but policy requires human review.

The gate is deterministic. It does not call a model, use a probabilistic score,
or silently infer missing evidence.

## Boundary

This is a pre-merge evidence gate. It does **not** replace:

- formal verification;
- CDC/RDC analysis;
- static timing analysis and timing closure;
- power, IR-drop, DRC, LVS, or physical sign-off;
- security review;
- human authorization for tape-out.

A gate decision is only as strong as the referenced evidence and configured
policy.

## Command

```bash
ibex-av gate-silicon-change \
  --request artifacts/gate/gate-request.json \
  --report artifacts/gate/gate-decision.json
```

Exit codes:

- `0`: `ALLOW`;
- `1`: `BLOCK`;
- `2`: invalid request or missing/malformed evidence;
- `3`: `ESCALATE`.

The standalone module exposes the same behavior:

```bash
python -m ibex_agent_verification.silicon_gate \
  --request artifacts/gate/gate-request.json \
  --report artifacts/gate/gate-decision.json
```

## Request contract

All evidence paths must be relative to the directory containing the request.
Absolute paths and `..` escapes are rejected.

```json
{
  "schema_version": 1,
  "change": {
    "request_id": "agent-change-001",
    "actor": {
      "type": "ai_agent",
      "name": "codex",
      "model": "gpt-example"
    },
    "base_commit": "BASE_SHA",
    "candidate_commit": "CANDIDATE_SHA",
    "changed_files": [
      "rtl/ibex_controller.sv"
    ],
    "risk_tags": [
      "control_flow"
    ]
  },
  "evidence": {
    "trace_comparison": "evidence/trace-comparison.json",
    "baseline_timing": "evidence/baseline-timing.json",
    "candidate_timing": "evidence/candidate-timing.json",
    "baseline_control_flow": "evidence/baseline-control-flow.json",
    "candidate_control_flow": "evidence/candidate-control-flow.json",
    "manifest": "evidence/manifest.json"
  },
  "policy": {
    "max_new_explained_timing_anomalies": 0,
    "max_new_delayed_redirects": 0,
    "manual_review_tags": [
      "clocking",
      "reset",
      "constraints",
      "security_boundary"
    ],
    "require_ai_model": true
  }
}
```

The request records who or what proposed the change. When `actor.type` is
`ai_agent` and `require_ai_model` is true, the model identifier is mandatory.
This is attribution, not a trust score.

## Required evidence

### Architectural comparison

`trace_comparison` must contain the normal comparator report. Any status other
than `MATCH` produces:

```text
BLOCK / ARCHITECTURAL_TRACE_MISMATCH
```

### Baseline and candidate timing reports

The gate reads `findings` and compares delay anomalies by cause:

- new `UNKNOWN` or null causes always block;
- new explained anomalies above policy budget block;
- new explained anomalies within a non-zero budget escalate.

The policy budget is not an automatic waiver. A tolerated regression still
requires a human decision.

### Baseline and candidate control-flow reports

The gate compares `delayed_redirects`:

- growth above policy budget blocks;
- growth within a non-zero budget escalates.

A `BRANCH_REDIRECT` record remains an architectural observation. It does not
become proof of a pipeline flush or misprediction.

### Evidence manifest

`manifest.project.commit` must equal `change.candidate_commit`. A mismatch
produces:

```text
BLOCK / EVIDENCE_COMMIT_MISMATCH
```

The gate also records SHA-256 and byte size for every referenced evidence file
in the decision report. This makes the exact inputs reviewable and replayable.

## Decision precedence

Decision severity is ordered:

```text
BLOCK > ESCALATE > ALLOW
```

One blocking reason cannot be hidden by several successful checks. If no block
exists but at least one escalation reason exists, the final result is
`ESCALATE`.

## Initial reason codes

Blocking reasons:

- `ARCHITECTURAL_TRACE_MISMATCH`;
- `EVIDENCE_COMMIT_MISMATCH`;
- `NEW_UNEXPLAINED_TIMING_ANOMALY`;
- `EXPLAINED_TIMING_REGRESSION_LIMIT_EXCEEDED`;
- `BRANCH_REDIRECT_DELAY_LIMIT_EXCEEDED`.

Escalation reasons:

- `EXPLAINED_TIMING_REGRESSION_REQUIRES_REVIEW`;
- `BRANCH_REDIRECT_DELAY_REQUIRES_REVIEW`;
- `MANUAL_REVIEW_TAG`.

Successful evidence:

- `NO_EVIDENCE_REGRESSION`.

## Example decision

```json
{
  "decision": "BLOCK",
  "request_id": "agent-change-001",
  "checks": {
    "architectural_trace": "MATCH",
    "evidence_commit_bound": true
  },
  "metrics": {
    "new_unknown_delay_anomalies": 1,
    "new_explained_delay_anomalies": 0,
    "new_delayed_redirects": 0
  },
  "reasons": [
    {
      "severity": "BLOCK",
      "code": "NEW_UNEXPLAINED_TIMING_ANOMALY",
      "message": "Candidate introduces delay anomalies without a supported cause.",
      "evidence": {
        "new_unknown_delay_anomalies": 1
      }
    }
  ]
}
```

## Recommended CI use

1. Build and simulate the trusted baseline revision.
2. Build and simulate the candidate revision in the same pinned environment.
3. Produce architectural comparison, timing, control-flow, and manifest reports.
4. Create the gate request with agent attribution and declared risk tags.
5. Run the gate.
6. Upload the request, decision, and all referenced evidence as one immutable
   bundle.
7. Permit merge only for `ALLOW`; route `ESCALATE` to named reviewers; reject
   `BLOCK`.

A future layer can add formal, lint, CDC, STA, power, and security reports as
additional explicit evidence adapters without changing the decision principle:
unsupported claims must never be promoted into proof.
