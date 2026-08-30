# ProofPath PoCI external consumer

Status: experimental cross-repository verification profile  
Consumer: `safal207/ibex-agent-verification`  
Producer: `safal207/ProofPath`

## Purpose

This profile proves that a repository outside ProofPath can consume an attested
PoCI quorum report, independently execute the pinned ProofPath multi-graph
builder, and reproduce the same causal, intent, authority, state-transition,
evidence, and time/continuity roots.

The chain is:

```text
ProofPath three-runner quorum
        ↓ keyless attested report
Ibex verifies producer workflow identity and subject bytes
        ↓
Ibex checks out exact ProofPath head
        ↓
Ibex independently recomputes source + six graphs + cells + product root
        ↓
Ibex external-consumer receipt
        ↓ keyless Ibex attestation
portable cross-repository evidence
```

## Two producer commits

The consumer pins two different SHA values deliberately:

- `code_sha` is the ProofPath PR head whose source and builder are executed;
- `attestation_source_sha` and `attestation_signer_sha` are the GitHub pull-request
  merge commit recorded in the Sigstore certificate and SLSA provenance.

Treating these as one value would either lose exact-head code binding or reject
valid GitHub pull-request attestations.

## Required checks

The consumer fails closed unless all of the following hold:

1. the copied quorum-report bytes match the pinned SHA-256 subject digest;
2. `gh attestation verify` validates the report against the exact ProofPath
   repository, signer workflow, source digest, signer digest, GitHub OIDC issuer,
   and GitHub-hosted runner boundary;
3. the external checkout resolves to the pinned ProofPath head;
4. the exported source JSON has the same domain-separated source digest;
5. the producer report is an accepted three-attestation quorum;
6. all six independently recomputed graph roots match;
7. the transition-cell commitment matches;
8. the computed multi-graph root matches;
9. the resulting Ibex receipt is itself keyless-attested.

## Mutation coverage

Focused tests cover:

- producer report byte substitution;
- absent producer attestation;
- wrong producer code commit;
- source mutation;
- authority-graph root substitution;
- transition-cell substitution;
- product-root substitution;
- non-accepting producer report;
- deterministic consumer receipt roots.

## Honest boundary

ProofPath and Ibex have separate repositories, commits, workflows, runners,
artifacts, and Sigstore identities. Both repositories are currently controlled
by the same GitHub account owner, so this is repository and workflow
independence, not independent organizational governance. The receipt proves
committed evidence consistency; it does not prove objective real-world truth.
