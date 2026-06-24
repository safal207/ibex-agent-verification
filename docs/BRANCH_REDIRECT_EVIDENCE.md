# Branch Redirect Evidence

The control-flow analyzer extracts evidence-backed redirects from the official
`ibex_tracer` instruction log.

## What it proves

For each pair of consecutive retired instructions, the analyzer calculates the
sequential PC from the previous instruction width:

```text
sequential_pc = from_pc + instruction_width_bytes
```

When the observed next PC differs and the previous mnemonic is a recognized
branch, jump, or return, the analyzer emits a `BRANCH_REDIRECT` record containing:

- source PC;
- sequential PC;
- observed target PC;
- branch/jump mnemonic;
- redirect kind;
- cycle gap and delay above the configured baseline;
- source line numbers from the raw trace.

Compressed instructions use a two-byte sequential increment; normal
instructions use four bytes.

## Critical causal boundary

A non-sequential PC after a recognized control-flow instruction proves that
architectural control flow redirected. It does **not** by itself prove:

- a branch misprediction;
- a pipeline flush;
- the number of flushed stages;
- a processor defect.

Those claims require explicit internal Ibex waveform or simulator signals. Every
redirect record therefore contains:

```json
{
  "primary_cause": "BRANCH_REDIRECT",
  "pipeline_flush_confirmed": false
}
```

This is intentional: the project records what the evidence supports and refuses
to promote an architectural observation into an unsupported microarchitectural
claim.

## Command

```bash
python -m ibex_agent_verification.control_flow \
  --input artifacts/ibex-e2e/raw/trace_core_00000000.log \
  --output artifacts/ibex-e2e/normalized/branch-redirects.jsonl \
  --report artifacts/ibex-e2e/normalized/branch-redirect-report.json
```

The command exits successfully when no redirects are present. The report status
will be `NO_REDIRECTS_FOUND`; an empty result is still valid evidence.

## Hosted evidence workflow

`Ibex Branch Redirect Evidence` runs after a successful `Ibex Verilator E2E`
workflow. It:

1. checks out the exact SHA used by the completed simulation;
2. downloads that run's reproducible evidence artifact;
3. analyzes the raw `trace_core_00000000.log`;
4. adds the redirect JSONL and summary report;
5. uploads a derived evidence bundle tied to the same commit SHA.

For safety, the post-processing workflow executes only for runs whose head
repository is this repository. It does not execute code from forked pull
requests under the elevated `workflow_run` token context.

## Next evidence layer

`PIPELINE_FLUSH` should be added only after the hosted waveform adapter captures
an explicit flush/redirect signal from the pinned Ibex revision and binds it to
the same retirement interval. The architectural redirect records in this module
provide the join keys for that future evidence.
