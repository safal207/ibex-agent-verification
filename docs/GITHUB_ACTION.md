# PythiaLabs Silicon Evidence Gate GitHub Action

Use this repository as a composite GitHub Action to evaluate a commit-bound gate request, write a JSON decision, publish outputs, add a job summary, and enforce merge policy.

## Minimal workflow

```yaml
steps:
  - uses: actions/checkout@v4
  - id: silicon_gate
    uses: safal207/ibex-agent-verification@main
    with:
      request: artifacts/gate/gate-request.json
      report: artifacts/gate/gate-decision.json
```

Pin a reviewed commit SHA or immutable release tag in production.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `request` | required | Gate request JSON path. |
| `report` | `artifacts/silicon-gate-decision.json` | Generated decision JSON path. |
| `python-version` | `3.12` | Python used by the action. |
| `fail-on-block` | `true` | Fail when the decision is `BLOCK`. |
| `fail-on-escalate` | `true` | Fail when the decision is `ESCALATE`. |

## Outputs

| Output | Meaning |
|---|---|
| `decision` | `ALLOW`, `BLOCK`, or `ESCALATE`. |
| `reason_codes` | Comma-separated deterministic reason codes. |
| `request_sha256` | SHA-256 of the gate request. |
| `report_sha256` | SHA-256 of the generated report. |
| `report_path` | Generated report path. |

## Observe before enforcing

```yaml
- id: silicon_gate
  uses: safal207/ibex-agent-verification@main
  with:
    request: artifacts/gate/gate-request.json
    fail-on-block: "false"
    fail-on-escalate: "false"
```

The action still publishes the decision, reason codes, hashes, annotation, JSON report, and job summary.

## Exit behavior

```text
ALLOW     -> success
BLOCK     -> exit 1 when fail-on-block=true
ESCALATE  -> exit 3 when fail-on-escalate=true
invalid   -> exit 2
```

Evidence evaluation and policy enforcement are separate steps, so a blocked pull request still preserves the outputs and report that explain the decision.

## Trust boundary

The action is deterministic and does not call an AI model. It rejects absolute evidence paths and traversal outside the request directory, hashes referenced evidence files, and requires manifest-to-candidate commit binding. It does not replace formal verification, CDC/RDC, STA, physical sign-off, security review, or tape-out authorization.

`Silicon Gate Action Smoke` verifies ALLOW, observe-only BLOCK, enforced BLOCK, outputs, summaries, and a 14-day evidence artifact on GitHub itself.
