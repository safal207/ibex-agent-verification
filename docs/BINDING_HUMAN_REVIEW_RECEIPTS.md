# Binding human-review receipts

`HumanReviewReceiptV1` converts a GitHub approval into recomputable evidence for
one exact pull-request head and one `PRE_MERGE` evaluation. The receipt is an
external governance input; it never authorizes merge.

```text
GitHub reviews + reviewer permissions + current PR head
                         ↓
              latest decisive review
                         ↓
        exact head / authority / time checks
                         ↓
             HumanReviewReceiptV1
                         ↓
             TemporalPhaseRelationV1
                         ↓
      SATISFIED or REQUIRED_EXTERNAL
```

## Binding conditions

A review is binding only when all of the following hold:

- the latest decisive review by that reviewer is `APPROVED`;
- the reviewer is not the pull-request author;
- repository permission is `write`, `maintain`, or `admin`;
- the review's `commit_id` equals the current PR head SHA;
- `submitted_at` is not later than the observation time;
- the review has not become `DISMISSED` or `CHANGES_REQUESTED`.

`COMMENTED` reviews are non-decisive. A comment after an approval does not erase
the approval, while a later change request or dismissal does.

## Head movement

```text
approval for head A
        ↓
new commit creates head B
        ↓
STALE_HEAD
        ↓
REQUIRED_EXTERNAL
```

The historical approval remains audit-visible, but it does not support the new
merge candidate.

## Time and phase

A successful receipt is wrapped in the temporal relation contract from PR #70:

```text
expected phase: PRE_MERGE
observed phase: PRE_MERGE
valid_from: review submitted_at
valid_until: current observation + 5 minutes
```

The narrow window forces every future merge-policy evaluation to reconstruct the
review relation instead of reusing an old positive result.

## Gate results

### SATISFIED

```json
{
  "status": "SATISFIED",
  "gate_satisfied": true,
  "merge_authorized": false,
  "permitted_next_transition": "EVALUATE_REPOSITORY_MERGE_POLICY"
}
```

### REQUIRED_EXTERNAL

Used when no current eligible approval exists. On draft pull requests this is a
normal pending state. On a ready-for-review pull request, the workflow fails the
binding check until an eligible exact-head approval is observed.

### NON_RECOMPUTABLE

Used for malformed, duplicate, or internally inconsistent review evidence. This
is a technical failure, not an external pending state.

## Workflow behavior

The workflow listens to pull-request head changes and review submissions,
edits, and dismissals. It:

1. fetches all review pages from GitHub;
2. resolves each reviewer's repository permission;
3. evaluates the gate against the exact current head;
4. publishes the receipt, temporal comparison, reasons, and gate record ID;
5. preserves `merge_authorized: false` in every result.
