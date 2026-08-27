import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.proofqa_response_integrity import (
    ResponseIntegrityError,
    digest_uri,
    verify_response_integrity_manifest,
)
from scripts.proofqa_transition_manifest import (
    TransitionManifestError,
    sha256_file,
    verify_transition_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
BASE_FIXTURE = ROOT / "tests/fixtures/proofqa/transition-manifest-bundle"
CASES_PATH = ROOT / "tests/fixtures/proofqa/response-integrity-cases.json"
RESPONSE_PROFILE = "org.liminal.trustworthy-transition.response.v0.1"
CLAIM_PROFILE = "org.liminal.trustworthy-transition.claim.v0.1"


class ProofQAResponseIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.cases = {case["case_id"]: case for case in cls.fixture["cases"]}

    def copy_bundle(self, destination: Path) -> Path:
        bundle = destination / "bundle"
        shutil.copytree(BASE_FIXTURE, bundle)
        return bundle

    def build_record(self, case_id: str) -> dict:
        case = copy.deepcopy(self.cases[case_id])
        claims = []
        for claim in case["claims"]:
            claim["claim_digest"] = digest_uri(
                {
                    "profile_id": CLAIM_PROFILE,
                    "claim_text": claim["claim_text"],
                }
            )
            claims.append(claim)
        response_text = case["response_text"]
        return {
            "schema_version": 1,
            "profile": self.fixture["profile"],
            "transition_id": self.fixture["transition_id"],
            "response_profile": RESPONSE_PROFILE,
            "response_text": response_text,
            "response_digest": digest_uri(
                {
                    "profile_id": RESPONSE_PROFILE,
                    "response_text": response_text,
                }
            ),
            "claims": claims,
            "overall_verdict": case["overall_verdict"],
            "verifier": {"id": "ibex:test-verifier", "version": "0.1"},
            "claim_boundary": (
                "Fixture verifies only deterministic comparison against the "
                "manifest-bound local observation."
            ),
        }

    def add_integrity_record(self, bundle: Path, record: dict) -> Path:
        path = bundle / "evidence/response-integrity.json"
        path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append(
            {
                "path": "evidence/response-integrity.json",
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
        manifest["files"] = sorted(manifest["files"], key=lambda item: item["path"])
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def verify(self, bundle: Path, integrity_path: Path) -> dict:
        return verify_response_integrity_manifest(
            evidence_dir=bundle,
            manifest_path=bundle / "manifest.json",
            transition_report_path=bundle / "transition-report.json",
            response_integrity_path=integrity_path,
            policy="verify",
        )

    def test_all_conformance_cases_preserve_independent_verdicts(self):
        for case_id, case in self.cases.items():
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as directory:
                bundle = self.copy_bundle(Path(directory))
                integrity_path = self.add_integrity_record(
                    bundle,
                    self.build_record(case_id),
                )
                receipt = self.verify(bundle, integrity_path)

                self.assertEqual(receipt["status"], "VERIFIED")
                self.assertEqual(
                    receipt["transition_manifest_receipt"]["status"],
                    "VERIFIED",
                )
                self.assertEqual(
                    receipt["response_integrity"]["overall_verdict"],
                    case["overall_verdict"],
                )
                self.assertEqual(
                    receipt["dimensions"],
                    {
                        "authority": "EXTERNAL_NOT_EVALUATED",
                        "execution": "OBSERVED",
                        "response_integrity": case["overall_verdict"],
                    },
                )
                self.assertEqual(receipt["manifest"]["files_checked"], 6)

    def test_verified_transition_does_not_repair_contradicted_response(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_bundle(Path(directory))
            path = self.add_integrity_record(
                bundle,
                self.build_record("fabricated_plausible_result"),
            )
            receipt = self.verify(bundle, path)

        self.assertEqual(
            receipt["transition_manifest_receipt"]["transition"]["status"],
            "VERIFIED",
        )
        self.assertEqual(receipt["dimensions"]["response_integrity"], "FAILED")
        self.assertEqual(
            receipt["response_integrity"]["claims"][0]["verdict"],
            "CONTRADICTED",
        )

    def test_declared_claim_verdict_must_match_deterministic_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_bundle(Path(directory))
            record = self.build_record("supported_exact_result")
            record["claims"][0]["verdict"] = "CONTRADICTED"
            record["overall_verdict"] = "FAILED"
            path = self.add_integrity_record(bundle, record)
            with self.assertRaisesRegex(ResponseIntegrityError, "verdict mismatch"):
                self.verify(bundle, path)

    def test_digest_binds_exact_response_and_claim_text(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_bundle(Path(directory))
            record = self.build_record("supported_exact_result")
            record["response_text"] = f" {record['response_text']} "
            record["response_digest"] = digest_uri(
                {
                    "profile_id": RESPONSE_PROFILE,
                    "response_text": record["response_text"],
                }
            )
            claim = record["claims"][0]
            claim["claim_text"] = f" {claim['claim_text']} "
            claim["claim_digest"] = digest_uri(
                {
                    "profile_id": CLAIM_PROFILE,
                    "claim_text": claim["claim_text"],
                }
            )
            path = self.add_integrity_record(bundle, record)

            receipt = self.verify(bundle, path)

        self.assertEqual(receipt["status"], "VERIFIED")
        self.assertEqual(
            receipt["response_integrity"]["response_digest"],
            record["response_digest"],
        )

    def test_top_level_array_fails_with_bounded_domain_error(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_bundle(Path(directory))
            path = self.add_integrity_record(bundle, [])
            with self.assertRaisesRegex(
                (TransitionManifestError, ResponseIntegrityError),
                "response integrity record must be a JSON object|"
                "response integrity record must be an object",
            ):
                self.verify(bundle, path)

    def test_unhashable_claim_id_fails_with_bounded_domain_error(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_bundle(Path(directory))
            record = self.build_record("supported_exact_result")
            record["claims"][0]["claim_id"] = []
            path = self.add_integrity_record(bundle, record)
            with self.assertRaisesRegex(
                ResponseIntegrityError,
                r"claims\[0\]\.claim_id must be a non-empty string",
            ):
                self.verify(bundle, path)

    def test_schema_and_runtime_pin_comparison_shapes(self):
        schema = json.loads(
            (ROOT / "schemas/proofqa-response-integrity-v0.1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        branches = schema["$defs"]["claim"]["properties"]["comparison"]["oneOf"]
        required_by_kind = {
            branch["properties"]["kind"]["const"]: set(branch["required"])
            for branch in branches
        }
        self.assertEqual(
            required_by_kind,
            {
                "JSON_POINTER_EQUALS": {"kind", "pointer", "expected_value"},
                "REFERENCE_PRESENT": {"kind"},
                "OUT_OF_SCOPE": {"kind"},
            },
        )
        self.assertTrue(all(branch["additionalProperties"] is False for branch in branches))

        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_bundle(Path(directory))
            record = self.build_record("missing_citation_binding")
            record["claims"][0]["comparison"]["pointer"] = "/status"
            path = self.add_integrity_record(bundle, record)
            with self.assertRaisesRegex(
                ResponseIntegrityError,
                "REFERENCE_PRESENT must contain only kind",
            ):
                self.verify(bundle, path)

    def test_tampered_integrity_bytes_fail_manifest_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.copy_bundle(Path(directory))
            path = self.add_integrity_record(
                bundle,
                self.build_record("supported_exact_result"),
            )
            path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(
                TransitionManifestError,
                "SHA256_MISMATCH|SIZE_MISMATCH",
            ):
                self.verify(bundle, path)

    def test_existing_four_role_bundle_remains_backward_compatible(self):
        receipt = verify_transition_manifest(
            evidence_dir=BASE_FIXTURE,
            manifest_path=BASE_FIXTURE / "manifest.json",
            transition_report_path=BASE_FIXTURE / "transition-report.json",
            policy="verify",
        )
        self.assertEqual(receipt["status"], "VERIFIED")
        self.assertEqual(receipt["manifest"]["files_checked"], 5)
        self.assertNotIn("response_integrity_ref", receipt["references"])


if __name__ == "__main__":
    unittest.main()
