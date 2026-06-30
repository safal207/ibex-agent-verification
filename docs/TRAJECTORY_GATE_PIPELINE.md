# Trajectory Gate Pipeline

The Trajectory Gate Pipeline is a dependency-light MVP for selecting the safest next pull-request transition from normalized multi-review evidence.

It treats each review source as a separate perspective:

- Codex;
- CodeRabbit;
- DeepSeek;
- exact-head CI.

The first version does not call GitHub APIs directly. It evaluates an already-normalized evidence payload and returns a deterministic report.

## Decisions

The selected transition is one of:

- `ALLOW`
- `BLOCK`
- `REPAIR`
- `SPLIT`
- `DEFER`
- `ROLLBACK`

## Fail-closed rules

The evaluator does not treat missing, skipped, stale, rate-limited, or failed gates as approval.

DeepSeek is modeled as a separate API-review gate. A skipped review job, missing API key, or failed API call blocks approval.

Reviewer outputs are only current if they apply to the PR head SHA.

## Minimal input

The minimal input contains repository metadata, PR number, current head SHA, and one normalized gate object for each required perspective.

## Output

The output report includes:

- selected transition;
- candidate transitions;
- normalized gate statuses;
- blocking and non-blocking findings;
- detected agreements between reviewers;
- blind spots;
- deterministic finding order;
- required next actions.

## Determinism

Findings are ordered by severity, reviewer, code, path, and line.

Duplicate findings from multiple reviewers are normalized into one finding and surfaced as reviewer agreement.

## Current scope

This MVP intentionally keeps GitHub collection and CrewAI orchestration out of the first layer. The next layer can add:

- GitHub collector for PR comments, reviews, and workflow runs;
- CrewAI perspective agents;
- PR live evaluation fixture;
- report persistence under the evidence directory.
