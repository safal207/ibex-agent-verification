import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ibex_agent_verification.cli import main
from ibex_agent_verification.trajectory_gate import evaluate_trajectory_gate


def base_record() -> dict:
    return {
        "repository": "safal207/ibex-agent-verification",
        "pr_number": 53,
        "head_sha": "abc123",
        "observed_at": "2026-06-28T17:10:00Z",
        "gates": {
            "codex": {
                "status": "PASS",
                "head_sha": "abc123",
                "applies_to_head": True,
                "blocking_findings": [],
                "non_blocking_findings": [],
            },
            "coderabbit": {
                "status": "PASS",
                "head_sha": "abc123",
                "applies_to_head": True,
                "blocking_findings": [],
                "non_blocking_findings": [],
            },
            "deepseek": {
                "status": "PASS",
                "head_sha": "abc123",
                "applies_to_head": True,
                "api_review_completed": True,
                "blocking_findings": [],
                "non_blocking_findings": [],
            },
            "ci": {
                "status": "PASS",
                "head_sha": "abc123",
                "applies_to_head": True,
                "exact_head": True,
                "failed_checks": [],
                "blocking_findings": [],
                "non_blocking_findings": [],
            },
        },
    }


class TrajectoryGateTests(unittest.TestCase):
    def test_all_gates_green_allows_current_head(self):
        result = evaluate_trajectory_gate(base_record())
        self.assertEqual(result["decision"], "ALLOW")
        self.assertEqual(result["gate_statuses"], {
            "codex": "PASS",
            "coderabbit": "PASS",
            "deepseek": "PASS",
            "ci": "PASS",
        })
        self.assertEqual(result["required_next_actions"], [])

    def test_deepseek_skipped_blocks_even_when_workflow_container_succeeded(self):
        record = base_record()
        record["gates"]["deepseek"].update(
            {
                "status": "SKIPPED",
                "api_review_completed": False,
                "review_job_skipped": True,
                "reason": "review job skipped",
            }
        )
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "BLOCK")
        self.assertEqual(result["gates"]["deepseek"]["status"], "BLOCKED")
        self.assertIn("rerun DeepSeek until a real API review completes", result["required_next_actions"])

    def test_missing_deepseek_api_key_blocks(self):
        record = base_record()
        record["gates"]["deepseek"].update(
            {
                "status": "PASS",
                "api_review_completed": False,
                "missing_api_key": True,
            }
        )
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "BLOCK")
        self.assertEqual(result["gates"]["deepseek"]["reason"], "missing DEEPSEEK_API_KEY")

    def test_stale_codex_review_defers(self):
        record = base_record()
        record["gates"]["codex"].update({"head_sha": "old", "applies_to_head": False})
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "DEFER")
        self.assertEqual(result["gates"]["codex"]["status"], "UNRESOLVED")
        self.assertIn("refresh codex output for current head SHA", result["required_next_actions"])

    def test_coderabbit_rate_limited_is_unresolved_not_approval(self):
        record = base_record()
        record["gates"]["coderabbit"].update(
            {"status": "RATE_LIMITED", "reason": "review not started due to rate limit"}
        )
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "DEFER")
        self.assertEqual(result["gates"]["coderabbit"]["status"], "UNRESOLVED")

    def test_exact_head_ci_failure_selects_repair(self):
        record = base_record()
        record["gates"]["ci"].update(
            {"status": "FAILED", "failed_checks": ["Ibex Verilator E2E"]}
        )
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "REPAIR")
        self.assertEqual(result["gates"]["ci"]["status"], "FAILED")
        self.assertIn("repair failing exact-head CI checks", result["required_next_actions"])

    def test_duplicate_findings_are_normalized_with_agreement(self):
        record = base_record()
        finding = {
            "severity": "critical",
            "code": "LIVE_BYTES_UNBOUND",
            "message": "release bytes are not bound to the runtime manifest",
            "path": "src/runtime.py",
            "line": 42,
        }
        record["gates"]["codex"]["blocking_findings"] = [finding]
        record["gates"]["coderabbit"]["blocking_findings"] = [finding]

        result = evaluate_trajectory_gate(record)

        self.assertEqual(result["decision"], "REPAIR")
        self.assertEqual(len(result["blocking_findings"]), 1)
        self.assertEqual(result["synthesis"]["agreements"][0]["reviewers"], ["codex", "coderabbit"])

    def test_finding_order_is_deterministic(self):
        record = base_record()
        record["gates"]["codex"]["blocking_findings"] = [
            {"severity": "minor", "code": "B", "message": "second", "path": "b.py", "line": 2},
            {"severity": "critical", "code": "A", "message": "first", "path": "a.py", "line": 1},
        ]
        first = evaluate_trajectory_gate(record)
        second = evaluate_trajectory_gate(record)
        self.assertEqual(first, second)
        self.assertEqual([item["code"] for item in first["blocking_findings"]], ["A", "B"])

    def test_cli_writes_report_and_returns_nonzero_for_block(self):
        record = base_record()
        record["gates"]["deepseek"].update(
            {"status": "SKIPPED", "api_review_completed": False, "review_job_skipped": True}
        )
        with tempfile.TemporaryDirectory() as tmp:
            record_path = Path(tmp) / "record.json"
            report_path = Path(tmp) / "report.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "evaluate-trajectory-gate",
                        "--record",
                        str(record_path),
                        "--report",
                        str(report_path),
                    ]
                )
            self.assertEqual(exit_code, 1)
            self.assertTrue(report_path.exists())
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["decision"], "BLOCK")
            self.assertEqual(stderr.getvalue(), "")
