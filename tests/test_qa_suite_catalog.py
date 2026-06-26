import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ibex_agent_verification.qa_benchmark import load_qa_suite
from scripts.build_qa_workflow_matrix import QAMatrixError, build_workflow_matrix, main


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "benchmarks/qa-suite-catalog.json"
MOBILE_SUITE_PATH = ROOT / "benchmarks/mobile-qa-engineer-v0.1.json"
CORE_SUITE_PATH = ROOT / "benchmarks/qa-engineer-core-v0.1.json"


class QASuiteCatalogTests(unittest.TestCase):
    def test_mobile_suite_covers_five_distinct_mobile_risks(self):
        suite = load_qa_suite(MOBILE_SUITE_PATH)
        self.assertEqual(suite["suite_id"], "mobile-qa-engineer-v0.1")
        self.assertEqual(len(suite["tasks"]), 5)
        self.assertEqual(
            {task["category"] for task in suite["tasks"]},
            {
                "lifecycle_state",
                "offline_sync",
                "permissions",
                "deep_linking",
                "data_migration",
            },
        )
        self.assertEqual(
            {task["max_completion_tokens"] for task in suite["tasks"]},
            {1024},
        )

    def test_catalog_builds_complete_suite_model_cross_product(self):
        matrix = build_workflow_matrix(CATALOG_PATH)
        include = matrix["include"]
        self.assertEqual(len(include), 4)
        self.assertEqual(
            {(row["suite_id"], row["model"]) for row in include},
            {
                ("qa-engineer-core-v0.1", "gpt-oss-120b"),
                ("qa-engineer-core-v0.1", "zai-glm-4.7"),
                ("mobile-qa-engineer-v0.1", "gpt-oss-120b"),
                ("mobile-qa-engineer-v0.1", "zai-glm-4.7"),
            },
        )
        self.assertEqual({row["task_count"] for row in include}, {5})
        self.assertEqual(
            {row["suite_slug"] for row in include},
            {"core-v0-1", "mobile-v0-1"},
        )
        self.assertEqual(
            {row["model_slug"] for row in include},
            {"gpt-oss-120b", "zai-glm-4-7"},
        )

    def test_cli_writes_compact_github_matrix_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "--catalog",
                        str(CATALOG_PATH),
                        "--github-output",
                        str(output),
                    ]
                )
            line = output.read_text(encoding="utf-8").strip()
        self.assertEqual(exit_code, 0)
        self.assertTrue(line.startswith("matrix="))
        matrix = json.loads(line.removeprefix("matrix="))
        self.assertEqual(len(matrix["include"]), 4)

    def test_catalog_rejects_id_and_task_count_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmarks = root / "benchmarks"
            benchmarks.mkdir()
            (benchmarks / CORE_SUITE_PATH.name).write_bytes(CORE_SUITE_PATH.read_bytes())
            catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            catalog["suites"] = [dict(catalog["suites"][0])]
            catalog["suites"][0]["suite_id"] = "wrong-suite-id"
            catalog_path = benchmarks / "qa-suite-catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(QAMatrixError, "suite_id mismatch"):
                build_workflow_matrix(catalog_path)

            catalog["suites"][0]["suite_id"] = "qa-engineer-core-v0.1"
            catalog["suites"][0]["expected_task_count"] = 6
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(QAMatrixError, "task count mismatch"):
                build_workflow_matrix(catalog_path)

    def test_catalog_rejects_path_escape_and_duplicate_slugs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmarks = root / "benchmarks"
            benchmarks.mkdir()
            catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            catalog["suites"] = [dict(catalog["suites"][0])]
            catalog["suites"][0]["path"] = "../outside.json"
            catalog_path = benchmarks / "qa-suite-catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(QAMatrixError, "stay inside the repository"):
                build_workflow_matrix(catalog_path)

            catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            catalog["models"][1]["slug"] = catalog["models"][0]["slug"]
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(QAMatrixError, "duplicate model slug"):
                build_workflow_matrix(catalog_path)

    def test_cli_returns_two_for_invalid_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text("{}", encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = main(["--catalog", str(path)])
        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
