import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from ibex_agent_verification.qa_benchmark import load_qa_suite
from scripts.qa_benchmark import main


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "benchmarks/qa-engineer-core-v0.1.json"
MODEL = "test-model"
PROVIDER = "cerebras"


def leaf_count(value) -> int:
    if isinstance(value, dict):
        return sum(leaf_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(leaf_count(item) for item in value)
    return 1


def possible_points(task: dict) -> int:
    return 1 + leaf_count(task["expected"])


def write_length_limited_capture(path: Path) -> None:
    events = [
        {"event": "request_start", "monotonic_ns": 1},
        {
            "event": "response_headers",
            "monotonic_ns": 2,
            "status_code": 200,
        },
        {
            "event": "chunk",
            "monotonic_ns": 3,
            "payload": {
                "choices": [
                    {
                        "delta": {"reasoning": "still reasoning"},
                        "finish_reason": None,
                    }
                ]
            },
        },
        {
            "event": "chunk",
            "monotonic_ns": 4,
            "payload": {
                "choices": [{"delta": {}, "finish_reason": "length"}],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 1024,
                    "total_tokens": 1044,
                    "completion_tokens_details": {"reasoning_tokens": 1024},
                },
            },
        },
        {"event": "request_end", "monotonic_ns": 5},
    ]
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


class QACompletionBudgetTests(unittest.TestCase):
    def test_all_v01_tasks_reserve_reasoning_safe_budget(self):
        suite = load_qa_suite(SUITE_PATH)
        self.assertEqual(
            {task["max_completion_tokens"] for task in suite["tasks"]},
            {1024},
        )

    def test_non_integer_oracle_is_explicit_not_ambiguous(self):
        suite = load_qa_suite(SUITE_PATH)
        task = next(task for task in suite["tasks"] if task["id"] == "test-design-boundaries")
        self.assertIn("use 18.5 as the explicit invalid non-integer probe", task["prompt"])
        self.assertEqual(task["expected"]["non_integer"], 18.5)

    def test_length_finish_reason_is_not_misreported_as_model_answer_failure(self):
        suite = load_qa_suite(SUITE_PATH)
        task = suite["tasks"][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            report = root / "score.json"
            write_length_limited_capture(capture)

            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "score",
                        "--suite",
                        str(SUITE_PATH),
                        "--task-id",
                        task["id"],
                        "--capture",
                        str(capture),
                        "--provider",
                        PROVIDER,
                        "--model",
                        MODEL,
                        "--report",
                        str(report),
                    ]
                )
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "OUTPUT_TRUNCATED")
        self.assertEqual(payload["finish_reasons"], ["length"])
        self.assertEqual(payload["diagnostic"]["code"], "OUTPUT_TRUNCATED")
        self.assertEqual(payload["diagnostic"]["max_completion_tokens"], 1024)
        self.assertEqual(payload["score"]["percent"], 0.0)
        self.assertEqual(payload["score"]["possible"], possible_points(task))
        self.assertEqual(payload["score"]["possible"], 5)
        self.assertNotIn("observed", payload)

    def test_summary_counts_truncation_with_full_suite_denominator(self):
        suite = load_qa_suite(SUITE_PATH)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            for task in suite["tasks"]:
                payload = {
                    "schema_version": 1,
                    "suite_id": suite["suite_id"],
                    "task_id": task["id"],
                    "category": task["category"],
                    "provider": PROVIDER,
                    "model": MODEL,
                    "status": "OUTPUT_TRUNCATED",
                    "score": {
                        "earned": 0,
                        "possible": possible_points(task),
                        "percent": 0.0,
                    },
                    "output": {"text_sha256": "0" * 64},
                }
                (reports / f"{task['id']}.json").write_text(
                    json.dumps(payload),
                    encoding="utf-8",
                )
            summary_path = root / "summary.json"
            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "summarize",
                        "--suite",
                        str(SUITE_PATH),
                        "--reports-dir",
                        str(reports),
                        "--provider",
                        PROVIDER,
                        "--model",
                        MODEL,
                        "--report",
                        str(summary_path),
                    ]
                )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["tasks_truncated"], 5)
        self.assertEqual(summary["tasks_invalid"], 5)
        self.assertEqual(summary["tasks_passed"], 0)
        self.assertEqual(summary["tasks_failed"], 0)
        self.assertEqual(summary["score"]["earned"], 0)
        self.assertEqual(summary["score"]["possible"], 29)
        self.assertEqual(summary["score"]["percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
