# Evidence Bundle Verification

`ibex-av verify-evidence` independently checks a downloaded evidence bundle against its generated `manifest.json`.

## Usage

When the manifest is stored at the bundle root:

```bash
ibex-av verify-evidence \
  --manifest artifacts/ibex-e2e/manifest.json \
  --report artifacts/ibex-e2e-verification.json
```

Keep the optional verification report outside the evidence directory. Adding it inside the bundle after verification would create a new file that is not part of the manifest inventory.

Use `--evidence-dir` when the manifest path and bundle root are supplied separately:

```bash
ibex-av verify-evidence \
  --evidence-dir artifacts/ibex-e2e \
  --manifest artifacts/ibex-e2e/manifest.json
```

## Verification contract

The verifier fails closed and checks that:

- the manifest uses supported schema version `1`;
- every manifest path is canonical, relative, unique, and contained by the bundle root;
- every listed item is a regular file rather than a symlink or directory;
- recorded byte sizes match;
- recorded lowercase SHA-256 values match;
- every bundle file other than the manifest is listed;
- no unlisted file was added after manifest generation.

The manifest does not list itself because a file cannot contain a stable digest of its own final bytes.

## Exit codes

- `0`: `VERIFIED` — the exact bundle inventory matches the manifest;
- `1`: `INTEGRITY_MISMATCH` — a file is missing, changed, or unlisted;
- `2`: `INVALID_INPUT` — the manifest is malformed, unsafe, unsupported, or unreadable.

A mismatch is evidence of bundle inconsistency. It does not by itself identify whether corruption, an incomplete download, accidental modification, or malicious tampering caused the difference.

## Hosted-artifact validation

During development, the verifier was exercised against two real hosted bundles:

- workflow run `28076903501`: `32/32` manifest entries verified;
- workflow run `28101955380`: `39/39` manifest entries verified, including the causal waveform bundle.

These checks validate the verifier against the recorded artifacts; they do not replace signature verification, trusted artifact storage, or human review of the evidence claims.
