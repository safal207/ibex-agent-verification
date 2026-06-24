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

Pin a reviewed commit SHA or immutable release tag in production. The action runs its stdlib-only Python code directly from the reviewed action source and currently targets Linux runners with `python3` available.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `request` | required | Gate request JSON path. |
| `report` | `artifacts/silicon-gate-decision.json` | Generated decision JSON path. |
| `fail_on_block` | `true` | Fail when the decision is `BLOCK`. |
| `fail_on_escalate` | `true` | Fail when the decision is `ESCALATE`. |

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
    fail_on_block: "false"
    fail_on_escalate: "false"
```

The action still publishes the decision, reason codes, hashes, annotation, JSON report, and job summary.

## Exit behavior

```text
ALLOW     -> success
BLOCK     -> exit 1 when fail_on_block=true
ESCALATE  -> exit 3 when fail_on_escalate=true
invalid   -> exit 2
```

Evidence evaluation and policy enforcement are separate steps, so a blocked pull request still preserves the outputs and report that explain the decision.

## Trust boundary

The action is deterministic and does not call an AI model. It rejects absolute evidence paths and traversal outside the request directory, hashes referenced evidence files, and requires manifest-to-candidate commit binding. It does not replace formal verification, CDC/RDC, STA, physical sign-off, security review, or tape-out authorization.

`Silicon Gate Action Smoke` verifies ALLOW, observe-only BLOCK, enforced BLOCK, outputs, summaries, and a 14-day evidence artifact on GitHub itself.
