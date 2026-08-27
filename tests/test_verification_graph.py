from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.verification_graph import (
    audit_workflow,
    build_plan,
    classify_changed_paths,
    finalize_plan,
    load_policy,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "qa/ibex-verification-graph.json"
WORKFLOW_PATH = ROOT / ".github/workflows/ibex-verification-graph.yml"
CLI_PATH = ROOT / "scripts/ibex_verification_graph.py"
HEAD = "a" * 40


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("ibex_verification_graph_cli", CLI_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load verification graph CLI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerificationGraphPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(POLICY_PATH)

    def test_documentation_only_change_is_l1(self) -> None:
        result = classify_changed_paths(["docs/IBEX_VERIFICATION_GRAPH.md"], self.policy)
        self.assertEqual(result["depth"], "L1")

    def test_runtime_change_is_l2(self) -> None:
        result = classify_changed_paths(
            ["src/ibex_agent_verification/integrations/crewai.py"],
            self.policy,
        )
        self.assertEqual(result["depth"], "L2")

    def test_authority_boundary_change_is_l3(self) -> None:
        result = classify_changed_paths(
            ["src/ibex_agent_verification/action_chain.py"],
            self.policy,
        )
        self.assertEqual(result["depth"], "L3")

    def test_workflow_change_is_l4(self) -> None:
        result = classify_changed_paths(
            [".github/workflows/ibex-verification-graph.yml"],
            self.policy,
        )
        self.assertEqual(result["depth"], "L4")

    def test_unknown_path_fails_closed_to_l3(self) -> None:
        result = classify_changed_paths(["future/unknown.contract"], self.policy)
        self.assertEqual(result["depth"], "L3")
        self.assertEqual(result["unknown_paths"], ["future/unknown.contract"])

    def test_highest_path_depth_wins(self) -> None:
        result = classify_changed_paths(
            ["docs/guide.md", ".github/workflows/ci.yml"],
            self.policy,
        )
        self.assertEqual(result["depth"], "L4")

    def test_l3_plan_requires_external_human_gate_without_merge_authority(self) -> None:
        plan = build_plan(
            ["src/ibex_agent_verification/action_chain.py"],
            HEAD,
            self.policy,
        )
        self.assertFalse(plan["merge_authorized"])
        self.assertIn("human_review", plan["decision"]["required_external_nodes"])
        self.assertIn("installed_wheel", plan["decision"]["required_ci_nodes"])

    def test_invalid_head_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            build_plan(["README.md"], "not-a-head", self.policy)


class VerificationGraphVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        policy = load_policy(POLICY_PATH)
        self.plan = build_plan(
            ["src/ibex_agent_verification/action_chain.py"],
            HEAD,
            policy,
        )

    def _successful_ci_results(self) -> dict[str, str]:
        return {
            node_id: "success"
            for node_id in self.plan["decision"]["required_ci_nodes"]
        }

    def test_successful_l3_graph_still_requires_external_gate(self) -> None:
        final = finalize_plan(self.plan, self._successful_ci_results())
        self.assertEqual(final["verdict"]["status"], "PASS_WITH_EXTERNAL_GATE")
        self.assertEqual(
            final["verdict"]["permitted_next_transition"],
            "REQUEST_BINDING_HUMAN_REVIEW",
        )
        self.assertFalse(final["merge_authorized"])

    def test_missing_required_result_blocks(self) -> None:
        results = self._successful_ci_results()
        results.pop("authority_invariants")
        final = finalize_plan(self.plan, results)
        self.assertEqual(final["verdict"]["status"], "BLOCK")
        self.assertIn("authority_invariants", final["verdict"]["blocking_nodes"])

    def test_failed_required_result_blocks(self) -> None:
        results = self._successful_ci_results()
        results["schema_vectors"] = "failure"
        final = finalize_plan(self.plan, results)
        self.assertEqual(final["verdict"]["status"], "BLOCK")
        self.assertIn("schema_vectors", final["verdict"]["blocking_nodes"])

    def test_unsupported_result_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            finalize_plan(self.plan, {"exact_head": "maybe"})


class VerificationGraphCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = _load_cli_module()
        self.policy = load_policy(POLICY_PATH)

    def test_github_outputs_follow_required_plan_nodes(self) -> None:
        plan = build_plan(
            ["src/ibex_agent_verification/action_chain.py"],
            HEAD,
            self.policy,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            self.cli._write_github_outputs(output, plan)
            values = dict(
                line.split("=", 1)
                for line in output.read_text(encoding="utf-8").splitlines()
            )
        self.assertEqual(values["depth"], "L3")
        self.assertEqual(values["require_schema"], "true")
        self.assertEqual(values["require_authority"], "true")
        self.assertEqual(values["require_wheel"], "true")
        self.assertEqual(values["require_workflow_security"], "false")
        self.assertEqual(values["require_human"], "true")

    def test_node_rename_fails_closed_instead_of_skipping_gate(self) -> None:
        plan = build_plan(
            ["src/ibex_agent_verification/action_chain.py"],
            HEAD,
            self.policy,
        )
        for node in plan["graph"]["nodes"]:
            if node["id"] == "schema_vectors":
                node["id"] = "schema_vectors_v2"
        plan["decision"]["required_ci_nodes"] = [
            "schema_vectors_v2" if node_id == "schema_vectors" else node_id
            for node_id in plan["decision"]["required_ci_nodes"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            with self.assertRaisesRegex(ValueError, "missing nodes"):
                self.cli._write_github_outputs(output, plan)


class VerificationGraphWorkflowTests(unittest.TestCase):
    def test_repository_workflow_passes_security_audit(self) -> None:
        report = audit_workflow(WORKFLOW_PATH)
        self.assertEqual(report, {
            "workflow": WORKFLOW_PATH.as_posix(),
            "status": "PASS",
            "findings": [],
        })

    def test_unpinned_action_is_blocked(self) -> None:
        unsafe = """
on:
  pull_request:
permissions: {}
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            path.write_text(unsafe, encoding="utf-8")
            report = audit_workflow(path)
        self.assertEqual(report["status"], "BLOCK")
        self.assertTrue(
            any("not pinned" in finding for finding in report["findings"])
        )

    def test_pinned_action_with_inline_comment_is_accepted(self) -> None:
        safe = """
on:
  pull_request:
permissions: {}
concurrency:
  group: ibex-verification-graph-${{ github.event.pull_request.number || github.ref }}
jobs:
  test:
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4
        with:
          repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          persist-credentials: false
      - run: echo merge_authorized=false
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            path.write_text(safe, encoding="utf-8")
            report = audit_workflow(path)
        self.assertEqual(report, {
            "workflow": path.as_posix(),
            "status": "PASS",
            "findings": [],
        })


if __name__ == "__main__":
    unittest.main()
