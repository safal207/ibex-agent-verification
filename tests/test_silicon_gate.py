import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.silicon_gate import (
    GateInputError,
    evaluate_gate,
    main,
)


class SiliconEvidenceGateTests(unittest.TestCase):
    def write_json(self, path: Path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def timing_report(self, *causes):
        findings = [
            {
                "step": index,
                "status": "DELAY_ANOMALY",
                "primary_cause": cause,
            }
            for index, cause in enumerate(causes, start=1)
        ]
        return {
            "status": "ANOMALY_DETECTED" if findings else "ON_TIME",
            "samples": max(1, len(findings)),
            "anomalies": len(findings),
            "findings": findings,
        }

    def build_request(
        self,
        root: Path,
        *,
        trace_status="MATCH",
        baseline_causes=(),
        candidate_causes=(),
        baseline_redirects=0,
        candidate_redirects=0,
        candidate_commit="candidate-sha",
        manifest_commit="candidate-sha",
        policy=None,
        risk_tags=None,
    ) -> Path:
        evidence_dir = root / "evidence"
        self.write_json(
            evidence_dir / "trace-comparison.json",
            {
                "status": trace_status,
                "expected_events": 10,
                "actual_events": 10,
                "first_mismatch_index": None,
                "differences": {},
            },
        )
        self.write_json(
            evidence_dir / "baseline-timing.json",
            self.timing_report(*baseline_causes),
        )
        self.write_json(
            evidence_dir / "candidate-timing.json",
            self.timing_report(*candidate_causes),
        )
        self.write_json(
            evidence_dir / "baseline-control-flow.json",
            {"status": "REDIRECTS_FOUND", "delayed_redirects": baseline_redirects},
        )
        self.write_json(
            evidence_dir / "candidate-control-flow.json",
            {"status": "REDIRECTS_FOUND", "delayed_redirects": candidate_redirects},
        )
        self.write_json(
            evidence_dir / "manifest.json",
            {"schema_version": 1, "project": {"commit": manifest_commit}},
        )

        request = {
            "schema_version": 1,
            "change": {
                "request_id": "agent-change-001",
                "actor": {
                    "type": "ai_agent",
                    "name": "codex",
                    "model": "gpt-test",
                },
                "base_commit": "base-sha",
                "candidate_commit": candidate_commit,
                "changed_files": ["rtl/ibex_controller.sv"],
                "risk_tags": risk_tags or [],
            },
            "evidence": {
                "trace_comparison": "evidence/trace-comparison.json",
                "baseline_timing": "evidence/baseline-timing.json",
                "candidate_timing": "evidence/candidate-timing.json",
                "baseline_control_flow": "evidence/baseline-control-flow.json",
                "candidate_control_flow": "evidence/candidate-control-flow.json",
                "manifest": "evidence/manifest.json",
            },
            "policy": policy
            or {
                "max_new_explained_timing_anomalies": 0,
                "max_new_delayed_redirects": 0,
                "manual_review_tags": ["clocking", "reset", "constraints"],
                "require_ai_model": True,
            },
        }
        request_path = root / "gate-request.json"
        self.write_json(request_path, request)
        return request_path

    def test_allow_when_evidence_is_bound_and_no_regression_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(Path(directory))
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "ALLOW")
        self.assertTrue(report["checks"]["evidence_commit_bound"])
        self.assertEqual(report["metrics"]["new_unknown_delay_anomalies"], 0)
        self.assertEqual(report["reasons"][0]["code"], "NO_EVIDENCE_REGRESSION")
        self.assertEqual(len(report["evidence_files"]), 6)

    def test_architectural_trace_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(Path(directory), trace_status="MISMATCH")
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "BLOCK")
        self.assertIn(
            "ARCHITECTURAL_TRACE_MISMATCH",
            [reason["code"] for reason in report["reasons"]],
        )

    def test_new_unknown_timing_anomaly_blocks_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(
                Path(directory), candidate_causes=("UNKNOWN",)
            )
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "BLOCK")
        self.assertEqual(report["metrics"]["new_unknown_delay_anomalies"], 1)
        self.assertIn(
            "NEW_UNEXPLAINED_TIMING_ANOMALY",
            [reason["code"] for reason in report["reasons"]],
        )

    def test_explained_regression_within_tolerance_escalates(self):
        policy = {
            "max_new_explained_timing_anomalies": 1,
            "max_new_delayed_redirects": 0,
            "manual_review_tags": [],
            "require_ai_model": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(
                Path(directory),
                candidate_causes=("MEMORY_WAIT",),
                policy=policy,
            )
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "ESCALATE")
        self.assertIn(
            "EXPLAINED_TIMING_REGRESSION_REQUIRES_REVIEW",
            [reason["code"] for reason in report["reasons"]],
        )

    def test_explained_regression_over_budget_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(
                Path(directory), candidate_causes=("MEMORY_WAIT",)
            )
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "BLOCK")
        self.assertIn(
            "EXPLAINED_TIMING_REGRESSION_LIMIT_EXCEEDED",
            [reason["code"] for reason in report["reasons"]],
        )

    def test_new_delayed_redirect_over_budget_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(
                Path(directory), baseline_redirects=2, candidate_redirects=3
            )
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "BLOCK")
        self.assertEqual(report["metrics"]["new_delayed_redirects"], 1)
        self.assertIn(
            "BRANCH_REDIRECT_DELAY_LIMIT_EXCEEDED",
            [reason["code"] for reason in report["reasons"]],
        )

    def test_declared_risk_tag_escalates_even_without_metric_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(Path(directory), risk_tags=["clocking"])
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "ESCALATE")
        reason = next(
            item for item in report["reasons"] if item["code"] == "MANUAL_REVIEW_TAG"
        )
        self.assertEqual(reason["evidence"]["matched_tags"], ["clocking"])

    def test_manifest_commit_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.build_request(
                Path(directory), manifest_commit="different-sha"
            )
            report = evaluate_gate(request)

        self.assertEqual(report["decision"], "BLOCK")
        self.assertIn(
            "EVIDENCE_COMMIT_MISMATCH",
            [reason["code"] for reason in report["reasons"]],
        )

    def test_evidence_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.build_request(root)
            payload = json.loads(request.read_text())
            payload["evidence"]["manifest"] = "../outside.json"
            request.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(GateInputError, "escapes"):
                evaluate_gate(request)

    def test_cli_exit_codes_distinguish_allow_block_and_escalate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allow_request = self.build_request(root / "allow")
            self.assertEqual(
                main(
                    [
                        "--request",
                        str(allow_request),
                        "--report",
                        str(root / "allow-report.json"),
                    ]
                ),
                0,
            )

            block_request = self.build_request(
                root / "block", trace_status="MISMATCH"
            )
            self.assertEqual(
                main(
                    [
                        "--request",
                        str(block_request),
                        "--report",
                        str(root / "block-report.json"),
                    ]
                ),
                1,
            )

            escalate_policy = {
                "max_new_explained_timing_anomalies": 1,
                "max_new_delayed_redirects": 0,
                "manual_review_tags": [],
                "require_ai_model": True,
            }
            escalate_request = self.build_request(
                root / "escalate",
                candidate_causes=("MEMORY_WAIT",),
                policy=escalate_policy,
            )
            self.assertEqual(
                main(
                    [
                        "--request",
                        str(escalate_request),
                        "--report",
                        str(root / "escalate-report.json"),
                    ]
                ),
                3,
            )


if __name__ == "__main__":
    unittest.main()
