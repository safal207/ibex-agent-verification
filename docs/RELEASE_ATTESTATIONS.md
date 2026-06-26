# Release Artifact Attestations

Future evidence releases publish a keyless Sigstore attestation in addition to the deterministic evidence ZIP, SHA-256 checksum, and release provenance JSON.

## What is signed

The release workflow submits three subjects to GitHub Artifact Attestations:

- the deterministic evidence ZIP;
- its `.sha256` sidecar;
- its `.provenance.json` sidecar.

GitHub issues a short-lived OIDC-backed Sigstore signing certificate to the release workflow. The resulting SLSA provenance attestation is stored in GitHub's attestation service and its Sigstore bundle is also attached to the GitHub Release as:

```text
vX.Y.Z-release-attestation.sigstore.json
```

No long-lived signing key is stored in the repository or in repository secrets.

## Online verification

Download the release ZIP, then run:

```bash
gh attestation verify vX.Y.Z-cerebras-live-evidence.zip \
  --repo safal207/ibex-agent-verification \
  --signer-workflow safal207/ibex-agent-verification/.github/workflows/release.yml \
  --deny-self-hosted-runners
```

This checks the artifact digest, GitHub repository identity, signer workflow identity, OIDC certificate chain, and transparency-backed signature.

## Bundled verification

The release also carries the exact Sigstore bundle emitted during signing. After downloading both files:

```bash
gh attestation verify vX.Y.Z-cerebras-live-evidence.zip \
  --repo safal207/ibex-agent-verification \
  --signer-workflow safal207/ibex-agent-verification/.github/workflows/release.yml \
  --deny-self-hosted-runners \
  --bundle vX.Y.Z-release-attestation.sigstore.json
```

The workflow performs both online and bundled verification after publication. It also downloads every release asset and compares it byte-for-byte with the local file that was uploaded.

## Trust boundary

A valid attestation proves that the exact artifact digest was signed by the named GitHub Actions workflow in this repository. It does not independently prove model quality, provider hardware behavior, silicon correctness, or that every claim inside an evidence bundle is scientifically sufficient. Those claims still depend on the repository's deterministic evidence and review process.

Release `v0.8.0` predates keyless attestation support and remains immutable. The attestation contract applies to newly published releases.
