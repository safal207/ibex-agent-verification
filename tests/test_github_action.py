import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ibex_agent_verification.github_action import main, run


class GitHubActionAdapterTests(unittest.TestCase):
    def write_json(self, path: Path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def build_request(self, root: Path, *, trace_status="MATCH") -> Path:
        evidence = root / "evidence"
        self.write_json(evidence / "trace.json", {"status": trace_status})
        timing = {"status": "ON_TIME", "anomalies": 0, "findings": []}
        self.write_json(evidence / "baseline-timing.json", timing)
        self.write_json(evidence / "candidate-timing.json", timing)
        control = {"status": "NO_REDIRECTS_FOUND", "delayed_redirects": 0}
        self.write_json(evidence / "baseline-control.json", control)
        self.write_json(evidence / "candidate-control.json", control)
        self.write_json(
            evidence / "manifest.json",
            {"schema_version": 1, "project": {"commit": "candidate-sha"}},
        )
        request = {
            "schema_version": 1,
            "change": {
                "request_id": "action-test-001",
                "actor": {
                    "type": "ai_agent",
                    "name": "test-agent",
                    "model": "test-model",
                },
                "base_commit": "base-sha",
                "candidate_commit": "candidate-sha",
                "changed_files": ["rtl/example.sv"],
                "risk_tags": [],
            },
            "evidence": {
                "trace_comparison": "evidence/trace.json",
                "baseline_timing": "evidence/baseline-timing.json",
                "candidate_timing": "evidence/candidate-timing.json",
                "baseline_control_flow": "evidence/baseline-control.json",
                "candidate_control_flow": "evidence/candidate-control.json",
                "manifest": "evidence/manifest.json",
            },
            "policy": {
                "max_new_explained_timing_anomalies": 0,
                "max_new_delayed_redirects": 0,
                "manual_review_tags": [],
                "require_ai_model": True,
            },
        }
        path = root / "gate-request.json"
        self.write_json(path, request)
        return path

    def test_allow_writes_outputs_summary_and_hashed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.build_request(root)
            report = root / "out" / "decision.json"
            output = root / "github-output.txt"
            summary = root / "step-summary.md"
            captured_stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(summary),
                },
                clear=False,
            ):
                with redirect_stdout(captured_stdout):
                    result = run(request, report)

            output_text = output.read_text()
            summary_text = summary.read_text()
            report_sha = hashlib.sha256(report.read_bytes()).hexdigest()
            annotation_text = captured_stdout.getvalue()

        self.assertEqual(result["decision"], "ALLOW")
        self.assertIn("decision=ALLOW", output_text)
        self.assertIn("reason_codes=NO_EVIDENCE_REGRESSION", output_text)
        self.assertIn(f"report_sha256={report_sha}", output_text)
        self.assertIn("## Silicon Evidence Gate", summary_text)
        self.assertIn("**Decision:** `ALLOW`", summary_text)
        self.assertIn("NO_EVIDENCE_REGRESSION", annotation_text)

    def test_block_is_published_without_adapter_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.build_request(root, trace_status="MISMATCH")
            report = root / "decision.json"
            output = root / "github-output.txt"
            captured_stdout = io.StringIO()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}, clear=False):
                with redirect_stdout(captured_stdout):
                    status = main(
                        ["--request", str(request), "--report", str(report)]
                    )
            payload = json.loads(report.read_text())
            output_text = output.read_text()
            annotation_text = captured_stdout.getvalue()

        self.assertEqual(status, 0)
        self.assertEqual(payload["decision"], "BLOCK")
        self.assertIn("decision=BLOCK", output_text)
        self.assertIn("ARCHITECTURAL_TRACE_MISMATCH", output_text)
        self.assertIn("ARCHITECTURAL_TRACE_MISMATCH", annotation_text)

    def test_invalid_input_returns_two(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "invalid.json"
            request.write_text("{}", encoding="utf-8")
            captured_stdout = io.StringIO()
            with redirect_stdout(captured_stdout):
                status = main(
                    [
                        "--request",
                        str(request),
                        "--report",
                        str(root / "decision.json"),
                    ]
                )
            annotation_text = captured_stdout.getvalue()

        self.assertEqual(status, 2)
        self.assertIn("INVALID_INPUT", annotation_text)
        self.assertIn("schema_version must be 1", annotation_text)


if __name__ == "__main__":
    unittest.main()
