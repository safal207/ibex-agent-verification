import json
import tempfile
import unittest
from pathlib import Path

from scripts import proofqa_gate_v3 as core
from scripts.proofqa_gate_v5 import (
    ProofQAGateV5Error,
    run,
    validate_manifest_receipt,
)
from scripts.proofqa_transition_manifest import verify_transition_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/proofqa"
BUNDLE = FIXTURES / "transition-manifest-bundle"
SUMMARY = FIXTURES / "summary-time-pass.json"


def receipt(policy: str = "verify") -> dict:
    return verify_transition_manifest(
        evidence_dir=BUNDLE,
        manifest_path=BUNDLE / "manifest.json",
        transition_report_path=BUNDLE / "transition-report.json",
        policy=policy,
    )


def normalized_transition() -> dict:
    raw = json.loads((BUNDLE / "transition-report.json").read_text())
    return {
        "transition_id": raw["transition_id"],
        "status": raw["status"],
        "phase": raw["phase"],
    }


class ProofQATransitionManifestGateTests(unittest.TestCase):
    def test_gate_report_schema_v4_binds_manifest_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "receipt.json"
            report_path = root / "gate.json"
            receipt_path.write_text(
                json.dumps(receipt(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            exit_code = run(
                {
                    "PROOFQA_SUMMARY_PATH": str(SUMMARY),
                    "PROOFQA_TRANSITION_REPORT_PATH": str(
                        BUNDLE / "transition-report.json"
                    ),
                    "PROOFQA_TRANSITION_POLICY": "require-verified",
                    "PROOFQA_TRANSITION_MANIFEST_POLICY": "verify",
                    "PROOFQA_TRANSITION_MANIFEST_RECEIPT_PATH": str(receipt_path),
                    "PROOFQA_MAX_P95_DURATION_MS": "1000",
                    "PROOFQA_REPORT_PATH": str(report_path),
                }
            )
            report = json.loads(report_path.read_text())

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["schema_version"], 4)
        self.assertEqual(report["decision"], "PASS")
        self.assertEqual(report["transition_manifest"]["status"], "VERIFIED")
        self.assertEqual(
            report["source"]["transition_manifest_sha256"],
            core._sha256(BUNDLE / "manifest.json"),
        )
        self.assertEqual(
            report["policy"]["transition_manifest_policy"],
            "verify",
        )

    def test_receipt_digest_must_match_consumed_transition_report(self):
        forged = receipt()
        forged["transition"]["report_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            ProofQAGateV5Error,
            "no longer matches",
        ):
            validate_manifest_receipt(
                receipt=forged,
                expected_policy="verify",
                transition=normalized_transition(),
                transition_path=BUNDLE / "transition-report.json",
            )

    def test_require_attested_rejects_pending_receipt(self):
        pending = receipt("require-attested")
        with self.assertRaisesRegex(
            ProofQAGateV5Error,
            "requires VERIFIED attestation",
        ):
            validate_manifest_receipt(
                receipt=pending,
                expected_policy="require-attested",
                transition=normalized_transition(),
                transition_path=BUNDLE / "transition-report.json",
            )

    def test_manifest_policy_cannot_run_when_transition_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ProofQAGateV5Error,
                "must be ignore when transition-policy is ignore",
            ):
                run(
                    {
                        "PROOFQA_SUMMARY_PATH": str(SUMMARY),
                        "PROOFQA_TRANSITION_POLICY": "ignore",
                        "PROOFQA_TRANSITION_MANIFEST_POLICY": "verify",
                        "PROOFQA_REPORT_PATH": str(Path(directory) / "gate.json"),
                    }
                )

    def test_report_cannot_overwrite_manifest_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt()), encoding="utf-8")
            with self.assertRaisesRegex(
                ProofQAGateV5Error,
                "must differ from every consumed source",
            ):
                run(
                    {
                        "PROOFQA_SUMMARY_PATH": str(SUMMARY),
                        "PROOFQA_TRANSITION_REPORT_PATH": str(
                            BUNDLE / "transition-report.json"
                        ),
                        "PROOFQA_TRANSITION_POLICY": "require-verified",
                        "PROOFQA_TRANSITION_MANIFEST_POLICY": "verify",
                        "PROOFQA_TRANSITION_MANIFEST_RECEIPT_PATH": str(
                            receipt_path
                        ),
                        "PROOFQA_REPORT_PATH": str(receipt_path),
                    }
                )


if __name__ == "__main__":
    unittest.main()
