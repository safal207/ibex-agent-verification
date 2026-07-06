# Ibex Verification Graph

`IBEX-VERIFY-GRAPH-001` makes the repository's verification architecture visible and executable on every pull request.

```text
authoritative changed paths
        ↓
L1-L4 depth decision
        ↓
exact-head binding
        ↓
graph contract + complete Python contract suite
        ↓
schema/vector recomputation
        ↓
fail-closed authority invariants
        ↓
installed-wheel runtime boundary
        ↓
workflow security + external human gate
        ↓
PASS / BLOCK / PASS_WITH_EXTERNAL_GATE
```

## Why this exists

A green `tests passed` badge is too weak for a repository that publishes verification and transition-authority contracts. Contributors need to see:

- which exact PR head was verified;
- why a change was classified as L1, L2, L3, or L4;
- which verification nodes were required;
- which nodes passed, failed, were skipped, or remain external;
- the machine-readable evidence behind the final graph verdict;
- that the graph itself never authorizes merge.

The workflow publishes both a GitHub Job Summary and downloadable JSON evidence.

## Depth policy

| Depth | Typical surface | Required posture |
|---:|---|---|
| L1 | documentation-only changes | exact head, graph self-test, complete contract suite |
| L2 | runtime, adapters, tests, examples | L1 plus schema/vector and authority checks |
| L3 | canonicalization, schemas, evidence, governance | L2 plus isolated installed-wheel verification and binding human review |
| L4 | workflows, release, attestation, privileged transition code | L3 plus workflow security audit |

Unknown paths fail closed to L3. The highest changed-path depth wins. Renamed files contribute both their old and new paths.

## Public checks

The workflow exposes separate, readable checks:

- **Build L1-L4 verification graph**
- **Exact head binding**
- **Graph contract**
- **Python contract suite**
- **Schema and vectors**
- **Authority invariants**
- **Installed wheel**
- **Workflow security**
- **Final graph verdict**

This separation matters: a contributor can see exactly which proof node failed instead of receiving one opaque red CI box.

## Contract-suite correction

The repository contains function-style `test_*` tests. `unittest discover` does not collect free test functions. The baseline CI therefore uses `pytest` and explicitly proves that a load-bearing verifier-depth regression is present in collection before running the complete suite.

This prevents a false-green state where the workflow is green while critical governance tests were never executed.

## Exact-head and fork boundary

Pull-request paths come from the paginated GitHub Pull Files API. The workflow checks out the exact head repository and SHA, including fork heads, with read-only permissions and disabled credential persistence.

```text
reported head SHA
        ==
checked-out git HEAD
        ==
head used by every graph node
```

## Machine-readable evidence

The plan and final graph artifacts include:

- contract and policy version;
- exact head SHA;
- authoritative changed paths;
- path-by-path depth reasons;
- required CI and external nodes;
- graph nodes and edges;
- node statuses;
- blocking nodes;
- permitted next transition;
- `merge_authorized: false`.

The final statuses are:

- `PASS`: all required CI nodes passed and no external gate is required;
- `PASS_WITH_EXTERNAL_GATE`: all required CI nodes passed, but binding human review remains required;
- `BLOCK`: at least one required CI node failed, was cancelled, skipped unexpectedly, or produced no result.

## Authority boundary

The graph has `verification-plan-only` authority.

It may:

- classify;
- require checks;
- bind evidence;
- block on missing proof;
- request external review.

It may not:

- approve a pull request;
- authorize merge;
- waive branch protection;
- convert a reviewer into an available reviewer;
- grant execution authority.

## Local use

```bash
python scripts/ibex_verification_graph.py validate-policy \
  --policy qa/ibex-verification-graph.json

python -m unittest discover \
  -s tests \
  -p 'test_verification_graph.py' \
  -v

python scripts/ibex_verification_graph.py plan \
  --policy qa/ibex-verification-graph.json \
  --files-json '["src/ibex_agent_verification/action_chain.py"]' \
  --head aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --output /tmp/ibex-plan.json \
  --summary /tmp/ibex-plan.md
```

The policy is deliberately conservative. False escalation is preferable to silently granting a shallow verification path to a deeper change.
