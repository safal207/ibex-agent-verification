import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/qa-model-verification.yml").read_text(
    encoding="utf-8"
)
SUITE = json.loads(
    (ROOT / "benchmarks/qa-engineer-core-v0.1.json").read_text(encoding="utf-8")
)


class QABenchmarkWorkflowTests(unittest.TestCase):
    def test_workflow_is_read_only_and_uses_pinned_actions(self):
        permissions = WORKFLOW.split("\nconcurrency:", 1)[0]
        self.assertIn("  contents: read", permissions)
        self.assertNotIn("contents: write", permissions)
        self.assertNotIn("id-token: write", permissions)
        self.assertIn(
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
            WORKFLOW,
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            WORKFLOW,
        )
        self.assertIn(
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            WORKFLOW,
        )
        self.assertNotIn("actions/checkout@v", WORKFLOW)
        self.assertNotIn("actions/setup-python@v", WORKFLOW)
        self.assertNotIn("actions/upload-artifact@v", WORKFLOW)

    def test_matrix_compares_exactly_two_models_without_fail_fast(self):
        self.assertIn("fail-fast: false", WORKFLOW)
        self.assertIn("- model: gpt-oss-120b", WORKFLOW)
        self.assertIn("- model: zai-glm-4.7", WORKFLOW)
        self.assertEqual(WORKFLOW.count("- model:"), 2)
        self.assertIn("qa-suite (${{ matrix.model }})", WORKFLOW)

    def test_suite_has_expected_qa_domains_and_five_tasks(self):
        self.assertEqual(SUITE["suite_id"], "qa-engineer-core-v0.1")
        self.assertEqual(len(SUITE["tasks"]), 5)
        self.assertEqual(
            {task["category"] for task in SUITE["tasks"]},
            {"bug_triage", "test_design", "api_testing", "sql", "log_analysis"},
        )
        self.assertIn('[[ "${#task_ids[@]}" -eq 5 ]]', WORKFLOW)

    def test_live_model_catalog_preflight_precedes_requests(self):
        catalog = WORKFLOW.index("Verify selected model in live Cerebras catalog")
        tasks = WORKFLOW.index("Run five model-scoped QA tasks")
        self.assertLess(catalog, tasks)
        self.assertIn("client.models.list()", WORKFLOW)
        self.assertIn("requested_model_available", WORKFLOW)
        self.assertIn("max_retries=0", WORKFLOW)
        self.assertIn("warm_tcp_connection=False", WORKFLOW)

    def test_each_task_gets_request_capture_verification_and_score(self):
        self.assertIn("scripts/qa_benchmark.py prepare", WORKFLOW)
        self.assertIn("ibex-av run-cerebras-inference", WORKFLOW)
        self.assertIn("ibex-av verify-evidence", WORKFLOW)
        self.assertIn("scripts/qa_benchmark.py score", WORKFLOW)
        self.assertIn('"$task_root/evidence/raw/capture.jsonl"', WORKFLOW)
        self.assertIn('"$task_root/score.json"', WORKFLOW)

    def test_wrong_answer_is_scored_without_arbitrary_quality_gate(self):
        self.assertNotIn("score_percent", WORKFLOW)
        self.assertNotIn("minimum_score", WORKFLOW)
        self.assertNotIn("winner", WORKFLOW.lower())
        self.assertNotIn("tasks_passed ==", WORKFLOW)
        self.assertIn("inference_exit_code", WORKFLOW)
        self.assertIn("scripts/qa_benchmark.py summarize", WORKFLOW)

    def test_outer_manifest_covers_scores_and_is_independently_verified(self):
        build = WORKFLOW.index("Build and independently verify outer benchmark manifest")
        summarize = WORKFLOW.index("Summarize deterministic QA scores")
        upload = WORKFLOW.index("Upload model-scoped QA evidence")
        self.assertLess(summarize, build)
        self.assertLess(build, upload)
        self.assertIn("scripts/build_qa_benchmark_bundle.py", WORKFLOW)
        self.assertIn('"$BUNDLE_DIR/manifest.json"', WORKFLOW)
        self.assertIn('"$MODEL_ROOT/qa-benchmark-verification.json"', WORKFLOW)

    def test_secret_is_environment_only_and_all_outputs_are_scanned(self):
        self.assertIn("CEREBRAS_API_KEY: ${{ secrets.CEREBRAS_API_KEY }}", WORKFLOW)
        self.assertNotIn("--api-key", WORKFLOW)
        self.assertIn('secret = os.environ["CEREBRAS_API_KEY"].encode("utf-8")', WORKFLOW)
        self.assertIn("credential value persisted in artifact", WORKFLOW)

    def test_model_artifacts_are_isolated(self):
        self.assertIn("MODEL_ROOT: artifacts/${{ matrix.slug }}", WORKFLOW)
        self.assertIn("BUNDLE_DIR: artifacts/${{ matrix.slug }}/qa-benchmark", WORKFLOW)
        self.assertIn(
            "name: ai-qa-engineer-${{ matrix.slug }}-${{ github.sha }}",
            WORKFLOW,
        )
        self.assertIn("path: artifacts/${{ matrix.slug }}/", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
