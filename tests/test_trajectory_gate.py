from copy import deepcopy
import unittest

from ibex_agent_verification.trajectory_gate import evaluate_trajectory_gate


def base_record() -> dict:
    return {
        "repository": "safal207/ibex-agent-verification",
        "pr_number": 53,
        "head_sha": "abc123",
        "observed_at": "2026-06-28T17:10:00Z",
        "gates": {
            "codex": {"status": "PASS", "head_sha": "abc123", "applies_to_head": True},
            "coderabbit": {"status": "PASS", "head_sha": "abc123", "applies_to_head": True},
            "deepseek": {
                "status": "PASS",
                "head_sha": "abc123",
                "applies_to_head": True,
                "api_review_completed": True,
            },
            "ci": {
                "status": "PASS",
                "head_sha": "abc123",
                "applies_to_head": True,
                "exact_head": True,
                "failed_checks": [],
            },
        },
    }


def selected_transition(result: dict) -> dict:
    return next(
        item for item in result["candidate_transitions"] if item["status"] == "SELECTED"
    )


class TrajectoryGateTests(unittest.TestCase):
    def test_all_gates_green_allows_current_head(self):
        result = evaluate_trajectory_gate(base_record())
        self.assertEqual(result["schema_version"], "trajectory-gate-report/v0.1")
        self.assertEqual(result["decision"], "ALLOW")
        self.assertEqual(result["best_next_transition"]["type"], "ALLOW")
        self.assertEqual(selected_transition(result)["type"], "ALLOW")
        self.assertEqual(
            result["gate_statuses"],
            {"codex": "PASS", "coderabbit": "PASS", "deepseek": "PASS", "ci": "PASS"},
        )
        self.assertEqual(result["required_next_actions"], [])

    def test_deepseek_skipped_blocks(self):
        record = base_record()
        record["gates"]["deepseek"].update(
            {"status": "SKIPPED", "api_review_completed": False, "review_job_skipped": True}
        )
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "BLOCK")
        self.assertEqual(result["best_next_transition"]["type"], "BLOCK")
        self.assertEqual(selected_transition(result)["reason"], "At least one fail-closed gate is blocked")
        self.assertEqual(result["gates"]["deepseek"]["status"], "BLOCKED")

    def test_deepseek_without_api_key_blocks(self):
        record = base_record()
        record["gates"]["deepseek"].update(
            {"api_review_completed": False, "missing_api_key": True}
        )
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "BLOCK")
        self.assertEqual(result["gates"]["deepseek"]["reason"], "missing DEEPSEEK_API_KEY")

    def test_stale_codex_review_defers(self):
        record = base_record()
        record["gates"]["codex"].update({"head_sha": "old", "applies_to_head": True})
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "DEFER")
        self.assertEqual(result["best_next_transition"]["type"], "DEFER")
        self.assertEqual(result["gates"]["codex"]["status"], "UNRESOLVED")
        self.assertFalse(result["gates"]["codex"]["applies_to_head"])

    def test_coderabbit_rate_limited_is_unresolved(self):
        record = base_record()
        record["gates"]["coderabbit"].update({"status": "RATE_LIMITED"})
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "DEFER")
        self.assertEqual(result["gates"]["coderabbit"]["status"], "UNRESOLVED")

    def test_exact_head_ci_failure_selects_repair(self):
        record = base_record()
        record["gates"]["ci"].update({"status": "FAILED", "failed_checks": ["e2e"]})
        result = evaluate_trajectory_gate(record)
        self.assertEqual(result["decision"], "REPAIR")
        self.assertEqual(result["best_next_transition"]["type"], "REPAIR")
        self.assertEqual(result["gates"]["ci"]["status"], "FAILED")

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
        first = evaluate_trajectory_gate(deepcopy(record))
        second = evaluate_trajectory_gate(deepcopy(record))
        self.assertEqual(first, second)
        self.assertEqual([item["code"] for item in first["blocking_findings"]], ["A", "B"])
