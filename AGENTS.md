# Instructions for Codex and other coding agents

## Mission

Build a reproducible verification layer around lowRISC Ibex. Prefer deterministic evidence over persuasive prose.

## Hard rules

1. Do not claim an Ibex bug from a model-generated explanation alone.
2. Preserve raw simulator output before normalization.
3. Every mismatch must identify the exact event index and differing fields.
4. Keep the dependency-free comparator core deterministic.
5. Do not silently change the trace schema.
6. Do not vendor or modify upstream Ibex code in this repository unless a task explicitly requires a pinned patch and attribution.
7. Never invent benchmark numbers, coverage numbers, simulator results, or supported instruction classes.
8. A failing external-tool integration may be reported as `BLOCKED`; it must never be converted into a passing synthetic result.

## Change protocol

Before editing:

- read `README.md`, `docs/ARCHITECTURE.md`, and `docs/VERIFICATION_PROTOCOL.md`;
- identify the smallest testable change;
- add or update a fixture and test;
- run `make test`;
- state what remains unverified.

## Preferred implementation order

1. deterministic parsers and schemas;
2. fixture-based tests;
3. command wrappers that preserve stdout/stderr and versions;
4. Ibex adapter;
5. reference oracle adapter;
6. minimization and AI-assisted generation.

## Definition of done

A change is done only when its behavior is testable locally, error modes are explicit, outputs are reviewable, and documentation does not overstate maturity.
