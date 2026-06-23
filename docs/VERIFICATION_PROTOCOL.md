# Verification Protocol

A result can be labeled `MISMATCH` only when all required evidence is present.

## Required manifest fields

- repository version
- Ibex upstream revision
- Ibex configuration
- compiler identity and version
- simulator identity and version
- program source and binary SHA-256
- random seed, if any
- exact commands
- raw DUT output
- raw oracle output
- normalized traces
- comparator report

## Result states

- `MATCH`: all normalized events match.
- `MISMATCH`: at least one deterministic semantic difference exists.
- `INVALID_INPUT`: trace or manifest is malformed.
- `BLOCKED`: an external dependency or tool failed.
- `INCONCLUSIVE`: evidence exists but the comparison contract does not cover the observed behavior.

## Reporting rule

`MISMATCH` is not automatically an Ibex defect. The discrepancy may be caused by the test, compiler, parser, oracle, unsupported behavior, or environment. A human must classify root cause before an upstream issue is opened.
