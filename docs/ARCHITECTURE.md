# Architecture

## Components

### 1. Test producer

Produces a bare-metal RISC-V program plus generation metadata. Initially manual fixtures; later deterministic generators and optional agent proposals.

### 2. Device-under-test runner

Runs the program on an explicitly identified Ibex configuration. It must capture:

- upstream commit or tag;
- Ibex configuration;
- simulator and compiler versions;
- binary hash;
- stdout, stderr, exit code;
- raw instruction trace;
- waveform path when enabled.

### 3. Reference oracle

Runs the same program against a reference model such as Spike or Sail. This layer is not implemented in the initial scaffold.

### 4. Trace normalizer

Converts runner-specific text into the repository JSONL contract. Raw inputs remain immutable.

### 5. Deterministic comparator

Compares event order and normalized architectural state. It emits a JSON report and stable exit code:

- `0`: traces match;
- `1`: semantic mismatch;
- `2`: invalid input or execution error.

### 6. Evidence bundle

Bundles contain a manifest, program or sanitized workload request, source hashes, environment versions when available, raw observations, normalized evidence, reports, and optional waveforms. The generic verifier checks the exact file inventory, sizes, and SHA-256 values independently of the adapter that produced the bundle.

### 7. Experimental inference evidence adapter

The first cross-domain adapter consumes a timestamped OpenAI-compatible streaming capture. It preserves the sanitized request and raw chunks, derives client-observed latency, and records provider-reported token usage without estimating missing throughput.

This layer is intentionally outside the Ibex silicon correctness contract. It demonstrates that the evidence bundle and integrity verifier can be reused for closed AI accelerator services while keeping the claim boundary explicit.

The first intended provider is Cerebras Cloud. A direct network runner, repeated statistical measurements, independent token counting, model-quality evaluation, and hardware provenance are not part of the initial slice.

## Trust boundary

AI-generated content, provider responses, benchmark descriptions, and performance claims are untrusted input. Deterministic parsers, comparators, metric derivation, and evidence manifests must remain independently executable.

An API-level inference capture proves only what the recorded client observation supports. It cannot prove the correctness of Cerebras WSE hardware, NVIDIA GPUs, OpenAI Jalapeño, or any other closed accelerator implementation.
