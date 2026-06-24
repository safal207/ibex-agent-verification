# Silicon Evidence Gate Demo

This demo proves the gate behavior with two complete, reviewable scenarios:

1. a clean AI-generated candidate that receives `ALLOW`;
2. a candidate with one new unexplained timing anomaly that receives `BLOCK`.

The purpose is not to claim silicon sign-off. The purpose is to demonstrate a
deterministic evidence boundary: an agent may propose a change, but the decision
is produced from explicit, commit-bound verification outputs.

## Run locally

Install the project, then run:

```bash
bash scripts/run_silicon_gate_demo.sh
```

Outputs are written to:

```text
artifacts/silicon-gate-demo/
├── allow/
│   ├── evidence/
│   ├── gate-request.json
│   └── gate-decision.json
├── block/
│   ├── evidence/
│   ├── gate-request.json
│   └── gate-decision.json
└── demo-summary.json
```

## ALLOW scenario

The clean scenario provides:

- an architectural comparator result with `status: MATCH`;
- no baseline or candidate timing anomalies;
- no growth in delayed branch redirects;
- a manifest whose project commit equals the candidate commit;
- explicit AI-agent and model attribution.

Expected result:

```json
{
  "decision": "ALLOW",
  "reasons": [
    {
      "severity": "ALLOW",
      "code": "NO_EVIDENCE_REGRESSION"
    }
  ]
}
```

## BLOCK scenario

The blocked scenario keeps the architectural trace matching and the evidence
manifest correctly bound. Its only intentional defect is one new timing finding
with `primary_cause: UNKNOWN`.

Expected result:

```json
{
  "decision": "BLOCK",
  "metrics": {
    "new_unknown_delay_anomalies": 1
  },
  "reasons": [
    {
      "severity": "BLOCK",
      "code": "NEW_UNEXPLAINED_TIMING_ANOMALY"
    }
  ]
}
```

This isolates the rule being demonstrated: an unexplained regression fails
closed even when the functional trace still matches.

## Hosted workflow

The `Silicon Evidence Gate Demo` workflow:

1. installs the package;
2. generates both evidence sets;
3. runs the public `ibex-av gate-silicon-change` CLI;
4. verifies the expected exit codes and reason codes;
5. writes `demo-summary.json` with SHA-256 hashes of both decision reports;
6. uploads the complete demo directory as a 14-day GitHub Actions artifact.

Artifact name:

```text
silicon-evidence-gate-demo-<commit-sha>
```

The workflow uses `if: always()` for upload so a partially generated bundle
remains inspectable when the demo fails.

## What this demonstrates

```text
AI-generated change
        ↓
commit-bound comparator / timing / control-flow / manifest evidence
        ↓
deterministic policy evaluation
        ↓
ALLOW or BLOCK with machine-readable reasons and hashed inputs
```

The demo intentionally avoids model scoring or natural-language judgment inside
the gate. The same request and evidence bytes always produce the same decision.

## Next production step

Replace the generated candidate evidence with reports from two real pinned Ibex
runs:

- trusted baseline revision;
- candidate revision containing an intentionally injected RTL or firmware
  regression.

The gate contract and decision layer can remain unchanged while the evidence
producer becomes fully hardware-backed.
