# PythiaLabs Silicon Evidence Gate GitHub Action

The repository can be consumed directly as a composite GitHub Action. A caller
provides one gate request plus the referenced evidence files; the action writes a
machine-readable report, publishes outputs, adds a job summary, and enforces the
selected merge policy.

## Minimal workflow

```yaml
name: Silicon evidence gate

on:
  pull_request:

permissions:
  contents: read

jobs:
  gate:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4

      - id: silicon_gate
        uses: safal207/ibex-agent-verification@main
        with:
          request: artifacts/gate/gate-request.json
          report: artifacts/gate/gate-decision.json

      - name: Upload evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: silicon-gate-${{ github.sha }}
          path: artifacts/gate/
```

For production use, pin the action to a reviewed commit SHA or immutable release
tag rather than a moving branch.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `request` | required | Gate request JSON path in the caller workspace. |
| `report` | `artifacts/silicon-gate-decision.json` | Generated decision JSON path. |
| `python-version` | `3.12` | Python used to install and run the gate. |
| `fail-on-block` | `true` | Fail the action when the decision is `BLOCK`. |
| `fail-on-escalate` | `true` | Fail the action when the decision is `ESCALATE`. |

Boolean policy inputs must be the lowercase strings `true` or `false`.

## Outputs

| Output | Meaning |
|---|---|
| `decision` | `ALLOW`, `BLOCK`, or `ESCALATE`. |
| `reason-codes` | Comma-separated deterministic reason codes. |
| `request-sha256` | SHA-256 of the request JSON. |
| `report-sha256` | SHA-256 of the generated decision JSON. |
| `report-path` | Generated report location. |

Example downstream policy:

```yaml
- name: Route escalation
  if: steps.silicon_gate.outputs.decision == 'ESCALATE'
  run: echo "Human verification review required"
```

## Observe before enforcing

A team can introduce the gate without immediately blocking pull requests:

```yaml
- id: silicon_gate
  uses: safal207/ibex-agent-verification@main
  with:
    request: artifacts/gate/gate-request.json
    fail-on-block: "false"
    fail-on-escalate: "false"
```

The action still writes the full report, outputs, annotation, and job summary.
The caller can measure current policy impact before enabling branch protection.

## Enforcement behavior

The evidence evaluation step itself exits successfully for every valid decision
so outputs and summaries are always published. A separate policy step enforces:

```text
ALLOW     -> success
BLOCK     -> exit 1 when fail-on-block=true
ESCALATE  -> exit 3 when fail-on-escalate=true
invalid   -> exit 2
```

This separation prevents a failed policy decision from hiding the evidence that
caused it.

## Job summary

Every valid run writes a GitHub job summary containing:

- final decision;
- request ID;
- report path and SHA-256;
- architectural comparison status;
- evidence-to-commit binding status;
- new unknown and explained timing anomalies;
- new delayed redirects;
- every deterministic reason code and message.

The summary is a convenience view. The JSON report and referenced evidence files
remain the source of record.

## Security and trust boundary

The action:

- installs the reviewed action repository from `GITHUB_ACTION_PATH`;
- does not call an AI model;
- does not download untrusted tools beyond the pinned GitHub runner actions and
  Python package installation from the checked-out action source;
- rejects absolute evidence paths and traversal outside the request directory;
- hashes every referenced evidence file;
- requires evidence-manifest binding to the candidate commit;
- does not claim formal verification, STA, physical sign-off, or tape-out safety.

The caller remains responsible for producing trustworthy evidence, pinning tool
versions, protecting workflow files, choosing reviewers, and configuring branch
protection.

## Smoke test

`Silicon Gate Action Smoke` validates the published contract on GitHub itself:

1. an `ALLOW` scenario passes and exposes `NO_EVIDENCE_REGRESSION`;
2. a `BLOCK` scenario can be observed without failing;
3. the same `BLOCK` scenario fails when enforcement is enabled;
4. all generated reports are uploaded as a 14-day artifact.
