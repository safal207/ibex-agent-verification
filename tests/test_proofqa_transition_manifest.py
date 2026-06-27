import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.proofqa_transition_manifest import (
    TransitionManifestError,
    finalize_attestation,
    sha256_file,
    verify_transition_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/proofqa/transition-manifest-bundle"


class ProofQATransitionManifestTests(unittest.TestCase):
    def copy_fixture(self, destination: Path) -> Path:
        bundle = destination / "bundle"
        shutil.copytree(FIXTURE, bundle)
        return bundle

    def verify(self, bundle: Path, *, policy: str = "verify") -> dict:
        return verify_transition_manifest(
            evidence_dir=bundle,
            manifest_path=bundle / "manifest.json",
            transition_report_path=bundle / "transition-report.json",
            policy=policy,
        )

    def test_verified_bundle_binds_report_and_four_distinct_evidence_files(self):
        receipt = self.verify(FIXTURE)
        self.assertEqual(receipt["status"], "VERIFIED")
        self.assertEqual(receipt["policy"], "verify")
        self.assertEqual(receipt["manifest"]["files_checked"], 5)
        self.assertEqual(
            receipt["transition"]["report_sha256"],
            sha256_file(FIXTURE / "transition-report.json"),
        )
        paths = {
            entry["path"]
            for entry in receipt["references"].values()
            if entry is not None
        }
        self.assertEqual(
            paths,
            {
                "evidence/intent.json",
                "evidence/action.json",
                "evidence/result.json",
                "evidence/verification.json",
            },
        )
        self.assertEqual(
            receipt["attestation"],
            {"required": False, "status": "NOT_REQUIRED"},
        )

    def test_tampered_evidence_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_fixture(Path(directory))
            path = bundle / "evidence/result.json"
            path.write_text(path.read_text() + " ", encoding="utf-8")
            with self.assertRaisesRegex(
                TransitionManifestError,
                "SHA256_MISMATCH|SIZE_MISMATCH",
            ):
                self.verify(bundle)

    def test_unlisted_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_fixture(Path(directory))
            (bundle / "evidence/extra.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(TransitionManifestError, "UNLISTED"):
                self.verify(bundle)

    def test_transition_report_must_itself_be_in_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_fixture(Path(directory))
            manifest = json.loads((bundle / "manifest.json").read_text())
            manifest["files"] = [
                entry
                for entry in manifest["files"]
                if entry["path"] != "transition-report.json"
            ]
            (bundle / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                TransitionManifestError,
                "UNLISTED|report itself must be listed",
            ):
                self.verify(bundle)

    def test_reference_must_use_canonical_manifest_scheme(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_fixture(Path(directory))
            report_path = bundle / "transition-report.json"
            report = json.loads(report_path.read_text())
            report["evidence"]["result_ref"] = "evidence/result.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest = json.loads((bundle / "manifest.json").read_text())
            for entry in manifest["files"]:
                if entry["path"] == "transition-report.json":
                    entry["size_bytes"] = report_path.stat().st_size
                    entry["sha256"] = sha256_file(report_path)
            (bundle / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                TransitionManifestError,
                "must use manifest:",
            ):
                self.verify(bundle)

    def test_evidence_roles_must_bind_distinct_files(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_fixture(Path(directory))
            report_path = bundle / "transition-report.json"
            report = json.loads(report_path.read_text())
            report["evidence"]["result_ref"] = report["evidence"]["action_ref"]
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest = json.loads((bundle / "manifest.json").read_text())
            for entry in manifest["files"]:
                if entry["path"] == "transition-report.json":
                    entry["size_bytes"] = report_path.stat().st_size
                    entry["sha256"] = sha256_file(report_path)
            (bundle / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                TransitionManifestError,
                "distinct manifest file",
            ):
                self.verify(bundle)

    def test_require_attested_receipt_stays_pending_until_two_verifications_exist(self):
        receipt = self.verify(FIXTURE, policy="require-attested")
        self.assertEqual(receipt["attestation"]["status"], "PENDING")

    def test_attestation_finalization_binds_bundle_and_both_verification_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "receipt.json"
            receipt_path.write_text(
                json.dumps(self.verify(FIXTURE, policy="require-attested")),
                encoding="utf-8",
            )
            bundle = root / "attestation.sigstore.json"
            online = root / "online.json"
            bundled = root / "bundled.json"
            bundle.write_text('{"dsseEnvelope":{"payload":"test"}}\n')
            online.write_text('[{"verificationResult":"verified"}]\n')
            bundled.write_text('[{"verificationResult":"verified"}]\n')

            finalized = finalize_attestation(
                receipt_path=receipt_path,
                online_report_path=online,
                bundled_report_path=bundled,
                attestation_bundle_path=bundle,
                repository="safal207/ibex-agent-verification",
                signer_workflow=(
                    "safal207/ibex-agent-verification/.github/workflows/"
                    "transition-evidence.yml"
                ),
            )

        self.assertEqual(finalized["attestation"]["status"], "VERIFIED")
        self.assertTrue(finalized["attestation"]["deny_self_hosted_runners"])
        self.assertEqual(
            finalized["attestation"]["bundle_sha256"],
            sha256_file(bundle),
        )


if __name__ == "__main__":
    unittest.main()
