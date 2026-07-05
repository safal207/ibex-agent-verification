# Temporal phase relations

`TemporalPhaseRelationV1` proves more than the existence of two graph artifacts.
It declares that a specific source artifact must support a specific target artifact
for one transition, during one lifecycle phase, inside one half-open validity
window.

```text
expected relation
      +
observed relation
      ↓
identity → phase → time → evidence freshness → outcome
      ↓
MATCH or fail-closed deviation
```

## Contracts

The runtime uses three self-describing contexts:

- `urn:ibex-agent-verification:temporal-phase-relation:v1`
- `urn:ibex-agent-verification:transition-observation:v1`
- `urn:ibex-agent-verification:expected-observed-transition-comparison:v1`

The expected relation binds:

- source and target artifact identities and SHA-256 digests;
- relation type and transition identity;
- expected lifecycle phase;
- `valid_from <= observed_at < valid_until`;
- maximum evidence age;
- expected outcome;
- recomputable evidence references.

The observation records the same artifact and transition identities, the phase and
time actually observed, the actual outcome, and the evidence used to reconstruct
that observation.

## Deterministic comparison order

The comparator applies one stable fail-closed precedence:

1. `NON_RECOMPUTABLE`
2. `MISSING_OBSERVATION`
3. `IDENTITY_MISMATCH`
4. `PHASE_MISMATCH`
5. `TEMPORAL_MISMATCH`
6. `STALE_EVIDENCE`
7. `OUTCOME_DEVIATION`
8. `MATCH`

This order prevents a later outcome comparison from hiding an earlier identity,
phase, time, or evidence failure.

## Authority boundary

A `MATCH` means that the observed relation supports the declared transition.
It does not authorize that transition:

```text
transition_supported = true
transition_authorized = false
permitted_next_transition = EVALUATE_POLICY_GATE
```

Every non-match emits:

```text
blocking = true
permitted_next_transition = BLOCK_AND_RECONCILE
```

Repository policy, branch protection, or another binding authority remains the
only component allowed to authorize the next transition.

## Example: stale review after a new commit

```text
expected:
  review receipt R supports PR head A during PRE_MERGE

observed:
  merge candidate uses PR head B with review receipt R

result:
  IDENTITY_MISMATCH
```

The review artifact still exists and the historical relation is still auditable,
but it no longer supports the current transition.

## Recompute the published vector

```bash
python scripts/ibex_temporal_phase_relation.py \
  --vector qa/temporal-phase-relation-vector.json \
  --output artifacts/temporal-phase-comparison.json
```

The published vector, relation identifiers, observation identifier, and comparison
identifier are all recomputed in CI from canonical JSON.
