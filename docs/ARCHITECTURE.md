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

Future bundles should contain a manifest, program, binary hash, environment versions, raw traces, normalized traces, report, and optional waveform.

## Trust boundary

AI-generated content is untrusted input. The comparator and evidence manifest must remain deterministic and independently executable.
