import json
import tempfile
import unittest
from pathlib import Path

from scripts.trusted_transition_artifact import TrustedTransitionArtifactError, sha256_file
from scripts.trusted_transition_artifact_audit import audit_signed_reference


REPOSITORY = "safal207/ibex-agent-verification"
COMMIT = "a" * 40
RUN_ID = 123456789
RUN_ATTEMPT = 2
SOURCE_WORKFLOW = ".github/workflows/ibex-evidence-promotion.yml"
SIGNER = f"{REPOSITORY}/.github/workflows/trusted-transition-artifact.yml"
CLAIM = (
    "This signed reference bundle verifies trusted cross-workflow artifact ingestion "
    "and manifest signing. It is not a production deployment claim."
)
FILES = [
    "evidence/action.json",
    "evidence/intent.json",
    "evidence/result.json",
    "evidence/verification.json",
    "source-provenance.json",
    "transition-report.json",
]


def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_chain(root: Path):
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
            "claim_boundary": CLAIM,
        },
    )
    for relative in FILES:
        path = bundle / relative
        if not path.exists():
            write(path, {"fixture": relative})
    write(
        bundle / "manifest.json",
        {
            "schema_version": 1,
            "files": [{"path": relative} for relative in FILES],
        },
    )
    manifest_sha = sha256_file(bundle / "manifest.json")
    artifact_digest = "sha256:" + "b" * 64
    write(
        root / "source-artifact-selection.json",
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
        root / "source-artifact-extraction.json",
        {
            "schema_version": 1,
            "status": "EXTRACTED",
            "files_checked": 6,
            "archive": {"digest": artifact_digest},
        },
    )
    write(
        root / "source-validation.json",
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
            "claim_boundary": CLAIM,
        },
    )
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


class TrustedTransitionArtifactAuditTests(unittest.TestCase):
    def test_complete_chain_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root)

            result = audit_signed_reference(
                root_dir=root,
                expected_repository=REPOSITORY,
                expected_commit=COMMIT,
                expected_run_id=RUN_ID,
                expected_run_attempt=RUN_ATTEMPT,
                expected_source_workflow=SOURCE_WORKFLOW,
                expected_signer_workflow=SIGNER,
            )

            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual(result["files_checked"], 6)
            self.assertEqual(result["source_workflow"], SOURCE_WORKFLOW)
            self.assertEqual(result["source_artifact"]["run_id"], RUN_ID)
            self.assertRegex(result["manifest_sha256"], r"^[0-9a-f]{64}$")

    def test_foreign_signer_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_chain(root)

            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "signer mismatch",
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
                TrustedTransitionArtifactError,
                "workflow mismatch",
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
