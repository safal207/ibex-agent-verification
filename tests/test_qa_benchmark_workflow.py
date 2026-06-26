import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/qa-model-verification.yml").read_text(
    encoding="utf-8"
)
CATALOG = json.loads(
    (ROOT / "benchmarks/qa-suite-catalog.json").read_text(encoding="utf-8")
)
CORE_SUITE = json.loads(
    (ROOT / "benchmarks/qa-engineer-core-v0.1.json").read_text(encoding="utf-8")
)
MOBILE_SUITE = json.loads(
    (ROOT / "benchmarks/mobile-qa-engineer-v0.1.json").read_text(encoding="utf-8")
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

    def test_live_pull_request_mode_is_explicit_and_same_repo_only(self):
        self.assertIn("  pull_request:", WORKFLOW)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            WORKFLOW,
        )
        self.assertIn(
            "startsWith(github.head_ref, 'verify/qa-suite-live-')",
            WORKFLOW,
        )
        self.assertIn("github.event_name != 'pull_request'", WORKFLOW)
        self.assertNotIn("pull_request_target:", WORKFLOW)

    def test_prepare_job_builds_matrix_from_validated_catalog(self):
        prepare = WORKFLOW.index("  prepare-matrix:")
        qa_job = WORKFLOW.index("  qa-suite:")
        self.assertLess(prepare, qa_job)
        self.assertIn("scripts/build_qa_workflow_matrix.py", WORKFLOW)
        self.assertIn("--catalog benchmarks/qa-suite-catalog.json", WORKFLOW)
        self.assertIn("--github-output \"$GITHUB_OUTPUT\"", WORKFLOW)
        self.assertIn("matrix: ${{ steps.matrix.outputs.matrix }}", WORKFLOW)
        self.assertIn(
            "matrix: ${{ fromJSON(needs.prepare-matrix.outputs.matrix) }}",
            WORKFLOW,
        )
        self.assertIn("needs: prepare-matrix", WORKFLOW)

    def test_catalog_defines_two_models_and_two_suites(self):
        self.assertEqual(
            {(item["provider"], item["model"]) for item in CATALOG["models"]},
            {
                ("cerebras", "gpt-oss-120b"),
                ("cerebras", "zai-glm-4.7"),
            },
        )
        self.assertEqual(
            {item["suite_id"] for item in CATALOG["suites"]},
            {"qa-engineer-core-v0.1", "mobile-qa-engineer-v0.1"},
        )
        self.assertNotIn("- model: gpt-oss-120b", WORKFLOW)
        self.assertNotIn("- model: zai-glm-4.7", WORKFLOW)
        self.assertIn("fail-fast: false", WORKFLOW)
        self.assertIn("max-parallel: 1", WORKFLOW)

    def test_core_and_mobile_suites_each_have_five_distinct_domains(self):
        self.assertEqual(len(CORE_SUITE["tasks"]), 5)
        self.assertEqual(len(MOBILE_SUITE["tasks"]), 5)
        self.assertEqual(
            {task["category"] for task in CORE_SUITE["tasks"]},
            {"bug_triage", "test_design", "api_testing", "sql", "log_analysis"},
        )
        self.assertEqual(
            {task["category"] for task in MOBILE_SUITE["tasks"]},
            {
                "lifecycle_state",
                "offline_sync",
                "permissions",
                "deep_linking",
                "data_migration",
            },
        )
        self.assertIn('[[ "${#task_ids[@]}" -eq "$EXPECTED_TASK_COUNT" ]]', WORKFLOW)
        self.assertNotIn('[[ "${#task_ids[@]}" -eq 5 ]]', WORKFLOW)

    def test_live_model_catalog_preflight_precedes_requests(self):
        catalog = WORKFLOW.index("Verify selected model in live Cerebras catalog")
        tasks = WORKFLOW.index("Run catalog-selected QA tasks")
        self.assertLess(catalog, tasks)
        self.assertIn("client.models.list()", WORKFLOW)
        self.assertIn("requested_model_available", WORKFLOW)
        self.assertIn("max_retries=0", WORKFLOW)
        self.assertIn("warm_tcp_connection=False", WORKFLOW)
        self.assertIn('if [[ "$PROVIDER" != "cerebras" ]]', WORKFLOW)

    def test_each_task_gets_request_capture_verification_and_score(self):
        self.assertIn("scripts/qa_benchmark.py prepare", WORKFLOW)
        self.assertIn("ibex-av run-cerebras-inference", WORKFLOW)
        self.assertIn("ibex-av verify-evidence", WORKFLOW)
        self.assertIn("scripts/qa_benchmark.py score", WORKFLOW)
        self.assertIn('"$task_root/evidence/raw/capture.jsonl"', WORKFLOW)
        self.assertIn('"$task_root/score.json"', WORKFLOW)
        self.assertIn('suite.get("suite_id") != os.environ["SUITE_ID"]', WORKFLOW)

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
        upload = WORKFLOW.index("Upload suite and model scoped QA evidence")
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

    def test_artifacts_are_isolated_by_suite_and_model(self):
        self.assertIn(
            "MODEL_ROOT: artifacts/${{ matrix.suite_slug }}/${{ matrix.model_slug }}",
            WORKFLOW,
        )
        self.assertIn(
            "BUNDLE_DIR: artifacts/${{ matrix.suite_slug }}/${{ matrix.model_slug }}/qa-benchmark",
            WORKFLOW,
        )
        self.assertIn(
            "name: ai-qa-engineer-${{ matrix.suite_slug }}-${{ matrix.model_slug }}-${{ github.sha }}",
            WORKFLOW,
        )
        self.assertIn(
            "path: artifacts/${{ matrix.suite_slug }}/${{ matrix.model_slug }}/",
            WORKFLOW,
        )


if __name__ == "__main__":
    unittest.main()
