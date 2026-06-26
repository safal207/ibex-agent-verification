from pathlib import Path
import unittest


WORKFLOW_PATH = Path(".github/workflows/cerebras-live-evidence.yml")
WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")


class CerebrasModelMatrixWorkflowTests(unittest.TestCase):
    def test_matrix_contains_baseline_and_glm_with_stable_slugs(self):
        self.assertIn("- model: gpt-oss-120b\n            slug: gpt-oss-120b", WORKFLOW)
        self.assertIn("- model: zai-glm-4.7\n            slug: zai-glm-4-7", WORKFLOW)
        self.assertEqual(WORKFLOW.count("- model:"), 2)
        self.assertIn("fail-fast: false", WORKFLOW)

    def test_each_model_uses_isolated_paths_and_artifact_names(self):
        self.assertIn("ARTIFACT_ROOT: artifacts/${{ matrix.slug }}", WORKFLOW)
        self.assertIn(
            "EVIDENCE_DIR: artifacts/${{ matrix.slug }}/cerebras-live-evidence",
            WORKFLOW,
        )
        self.assertIn(
            "REQUEST_PATH: artifacts/${{ matrix.slug }}/cerebras-live-request.json",
            WORKFLOW,
        )
        self.assertIn(
            "name: cerebras-live-evidence-${{ matrix.slug }}-${{ github.sha }}",
            WORKFLOW,
        )
        self.assertIn("path: artifacts/${{ matrix.slug }}/", WORKFLOW)

    def test_live_catalog_preflight_runs_before_inference(self):
        catalog_index = WORKFLOW.index(
            "- name: Verify model is currently listed by Cerebras"
        )
        request_index = WORKFLOW.index("- name: Prepare bounded streaming request")
        inference_index = WORKFLOW.index("- name: Run one live Cerebras stream")
        self.assertLess(catalog_index, request_index)
        self.assertLess(request_index, inference_index)
        self.assertIn("client.models.list()", WORKFLOW)
        self.assertIn("requested_model_available", WORKFLOW)
        self.assertIn("max_retries=0", WORKFLOW)
        self.assertIn("warm_tcp_connection=False", WORKFLOW)

    def test_comparison_uses_same_bounded_request_contract(self):
        self.assertIn(
            'source = Path("tests/fixtures/inference/openai_request.json")',
            WORKFLOW,
        )
        self.assertIn('request["model"] = os.environ["CEREBRAS_MODEL"]', WORKFLOW)
        self.assertIn('request["max_completion_tokens"] = 64', WORKFLOW)
        self.assertIn('--timeout-seconds 60', WORKFLOW)
        self.assertIn('"temperature": 0', Path(
            "tests/fixtures/inference/openai_request.json"
        ).read_text(encoding="utf-8"))

    def test_evidence_is_bound_to_exact_matrix_model(self):
        self.assertIn(
            'observed_model = manifest.get("workload", {}).get("model")',
            WORKFLOW,
        )
        self.assertIn('expected_model = os.environ["CEREBRAS_MODEL"]', WORKFLOW)
        self.assertIn("evidence model mismatch", WORKFLOW)

    def test_secret_stays_in_environment_and_is_scanned_from_outputs(self):
        self.assertIn("CEREBRAS_API_KEY: ${{ secrets.CEREBRAS_API_KEY }}", WORKFLOW)
        self.assertNotIn("--api-key", WORKFLOW)
        self.assertIn('secret = os.environ["CEREBRAS_API_KEY"].encode("utf-8")', WORKFLOW)
        self.assertIn("credential value persisted in artifact", WORKFLOW)

    def test_claim_boundary_does_not_turn_latency_into_quality_claim(self):
        self.assertIn(
            "no internal hardware, model-quality, or RTL claim",
            WORKFLOW,
        )


if __name__ == "__main__":
    unittest.main()
