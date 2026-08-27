import json
import tempfile
import unittest
from pathlib import Path

from scripts.trusted_transition_artifact import (
    TrustedTransitionArtifactError,
    sha256_file,
)
from scripts.trusted_transition_artifact_audit import (
    EXPECTED_ATTESTED_FILES,
    audit_signed_reference,
)


REPOSITORY = "safal207/ibex-agent-verification"
COMMIT = "a" * 40
RUN_ID = 123456789
RUN_ATTEMPT = 2
SOURCE_WORKFLOW = ".github/workflows/github-release-runtime-verification.yml"
SIGNER = f"{REPOSITORY}/.github/workflows/trusted-transition-artifact.yml"
CLAIM = (
    "This signed reference bundle verifies trusted cross-workflow artifact ingestion "
    "and manifest signing. It is not a production deployment claim."
)
RUNTIME_CLAIM = (
    "This verifies publication and live re-download of a customer release asset. "
    "It does not prove installation or runtime behavior, and it is not a physical "
    "production execution claim."
)
DESTINATION_ID = (
    "github-actions:repository-id:1:environment:ibex-runtime-verification:"
    f"workflow-run:{RUN_ID}:attempt:{RUN_ATTEMPT}:runner:github-hosted-ubuntu-24.04"
)


def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_chain(root: Path, *, claim=CLAIM):
    bundle = root / "bundle"
    write(
        bundle / "source-provenance.json",
        {
            "schema_version": 1,
            "kind": "production-transition-source",
            "repository": REPOSITORY,
            "source_commit": COMMIT,
            "deployment": {
                "workflow": SOURCE_WORKFLOW,
                "run_id": RUN_ID,
                "run_attempt": RUN_ATTEMPT,
            },
            "destination": {"identity": DESTINATION_ID},
            "claim_boundary": claim,
        },
    )
    for relative in EXPECTED_ATTESTED_FILES:
        path = bundle / relative
        if path.exists():
            continue
        if relative in {
            "signer/source-artifact-selection.json",
            "signer/source-artifact-extraction.json",
            "signer/runtime-observation.json",
            "signer/source-validation.json",
        }:
            continue
        write(path, {"fixture": relative})

    artifact_digest = "sha256:" + "b" * 64
    write(
        bundle / "signer/source-artifact-selection.json",
        {
            "schema_version": 1,
            "status": "SELECTED",
            "repository": REPOSITORY,
            "head_sha": COMMIT,
            "workflow": SOURCE_WORKFLOW,
            "run_id": RUN_ID,
            "run_attempt": RUN_ATTEMPT,
            "artifact": {
                "id": 987654321,
                "name": f"proofqa-transition-source-{COMMIT}",
                "digest": artifact_digest,
            },
        },
    )
    write(
        bundle / "signer/source-artifact-extraction.json",
        {
            "schema_version": 1,
            "status": "EXTRACTED",
            "files_checked": 6,
            "archive": {"digest": artifact_digest},
        },
    )
    write(
        bundle / "signer/runtime-observation.json",
        {
            "schema_version": 1,
            "status": "OBSERVED",
            "repository": REPOSITORY,
            "source_commit": COMMIT,
            "runtime_workflow": SOURCE_WORKFLOW,
            "runtime_run_id": RUN_ID,
            "runtime_run_attempt": RUN_ATTEMPT,
            "destination_id": DESTINATION_ID,
            "claim_boundary": claim,
        },
    )
    write(
        bundle / "signer/source-validation.json",
        {
            "schema_version": 1,
            "status": "VALIDATED",
            "repository": REPOSITORY,
            "source_commit": COMMIT,
            "deployment": {
                "workflow": SOURCE_WORKFLOW,
                "run_id": RUN_ID,
                "run_attempt": RUN_ATTEMPT,
            },
            "files_checked": 6,
            "claim_boundary": claim,
        },
    )
    write(
        bundle / "manifest.json",
        {
            "schema_version": 1,
            "files": [
                {"path": relative}
                for relative in sorted(EXPECTED_ATTESTED_FILES)
            ],
        },
    )
    manifest_sha = sha256_file(bundle / "manifest.json")
    write(
        root / "manifest-receipt.json",
        {
            "attestation": {
                "status": "VERIFIED",
                "repository": REPOSITORY,
                "signer_workflow": SIGNER,
                "deny_self_hosted_runners": True,
            }
        },
    )
    write(root / "manifest.sigstore.json", {"mediaType": "fixture"})
    write(
        root / "proofqa-gate-report.json",
        {
            "schema_version": 4,
            "decision": "PASS",
            "transition_manifest": {"attestation": {"status": "VERIFIED"}},
            "source": {"transition_manifest_sha256": manifest_sha},
        },
    )


def audit(root: Path):
    return audit_signed_reference(
        root_dir=root,
        expected_repository=REPOSITORY,
        expected_commit=COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_source_workflow=SOURCE_WORKFLOW,
        expected_signer_workflow=SIGNER,
    )


class TrustedTransitionArtifactAuditTests(unittest.TestCase):
    def test_complete_chain_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root)
            result = audit(root)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual(
                result["files_checked"], len(EXPECTED_ATTESTED_FILES)
            )
            self.assertEqual(result["source_workflow"], SOURCE_WORKFLOW)
            self.assertEqual(result["source_artifact"]["run_id"], RUN_ID)
            self.assertRegex(result["manifest_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(
                result["runtime_observation_sha256"], r"^[0-9a-f]{64}$"
            )

    def test_runtime_limited_production_claim_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root, claim=RUNTIME_CLAIM)
            result = audit(root)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual(result["claim_boundary"], RUNTIME_CLAIM)

    def test_vague_production_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root, claim="This release is production ready.")
            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "explicit production limitation",
            ):
                audit(root)

    def test_unsigned_observation_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root)
            payload = json.loads(
                (root / "bundle/manifest.json").read_text(encoding="utf-8")
            )
            payload["files"] = [
                item
                for item in payload["files"]
                if item["path"] != "signer/runtime-observation.json"
            ]
            write(root / "bundle/manifest.json", payload)
            with self.assertRaisesRegex(
                TrustedTransitionArtifactError, "exact source plus signer"
            ):
                audit(root)

    def test_foreign_observation_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root)
            path = root / "bundle/signer/runtime-observation.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["runtime_run_id"] = RUN_ID + 1
            write(path, payload)
            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "observation workflow identity mismatch",
            ):
                audit(root)

    def test_foreign_signer_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root)
            with self.assertRaisesRegex(
                TrustedTransitionArtifactError, "signer mismatch"
            ):
                audit_signed_reference(
                    root_dir=root,
                    expected_repository=REPOSITORY,
                    expected_commit=COMMIT,
                    expected_run_id=RUN_ID,
                    expected_run_attempt=RUN_ATTEMPT,
                    expected_source_workflow=SOURCE_WORKFLOW,
                    expected_signer_workflow=(
                        f"{REPOSITORY}/.github/workflows/foreign.yml"
                    ),
                )

    def test_foreign_source_workflow_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root)
            with self.assertRaisesRegex(
                TrustedTransitionArtifactError, "workflow mismatch"
            ):
                audit_signed_reference(
                    root_dir=root,
                    expected_repository=REPOSITORY,
                    expected_commit=COMMIT,
                    expected_run_id=RUN_ID,
                    expected_run_attempt=RUN_ATTEMPT,
                    expected_source_workflow=".github/workflows/foreign.yml",
                    expected_signer_workflow=SIGNER,
                )


if __name__ == "__main__":
    unittest.main()
