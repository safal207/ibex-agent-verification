import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ibex_agent_verification.qa_benchmark import (
    QABenchmarkError,
    build_qa_request,
    load_qa_suite,
    score_qa_capture,
    summarize_qa_reports,
)
from scripts.qa_benchmark import main


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = REPOSITORY_ROOT / "benchmarks/qa-engineer-core-v0.1.json"
MODEL = "test-model"
PROVIDER = "cerebras"


def write_capture(path: Path, text: str, *, complete: bool = True) -> None:
    if complete:
        events = [
            {"event": "request_start", "monotonic_ns": 1_000_000_000},
            {
                "event": "response_headers",
                "monotonic_ns": 1_010_000_000,
                "status_code": 200,
            },
            {
                "event": "chunk",
                "monotonic_ns": 1_020_000_000,
                "payload": {"choices": [{"delta": {"content": text[: len(text) // 2]}}]},
            },
            {
                "event": "chunk",
                "monotonic_ns": 1_030_000_000,
                "payload": {
                    "choices": [{"delta": {"content": text[len(text) // 2 :]}}],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                },
            },
            {"event": "request_end", "monotonic_ns": 1_040_000_000},
        ]
    else:
        events = [
            {"event": "request_start", "monotonic_ns": 1},
            {
                "event": "request_error",
                "monotonic_ns": 2,
                "error": "provider timeout",
            },
        ]
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


class QABenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.suite = load_qa_suite(SUITE_PATH)

    def test_suite_has_five_unique_qa_categories(self):
        self.assertEqual(self.suite["suite_id"], "qa-engineer-core-v0.1")
        self.assertEqual(len(self.suite["tasks"]), 5)
        self.assertEqual(
            {task["category"] for task in self.suite["tasks"]},
            {"bug_triage", "test_design", "api_testing", "sql", "log_analysis"},
        )
        self.assertEqual(
            len({task["id"] for task in self.suite["tasks"]}),
            len(self.suite["tasks"]),
        )

    def test_request_is_bounded_and_model_bound(self):
        task = self.suite["tasks"][0]
        request = build_qa_request(
            suite=self.suite,
            task_id=task["id"],
            model=MODEL,
        )
        self.assertEqual(request["model"], MODEL)
        self.assertEqual(request["temperature"], 0)
        self.assertTrue(request["stream"])
        self.assertEqual(request["stream_options"], {"include_usage": True})
        self.assertEqual(request["max_completion_tokens"], task["max_completion_tokens"])
        self.assertIn("no Markdown", request["messages"][0]["content"])
        self.assertEqual(request["messages"][1]["content"], task["prompt"])

    def test_perfect_response_passes_with_full_score(self):
        task = self.suite["tasks"][0]
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.jsonl"
            write_capture(capture, json.dumps(task["expected"], separators=(",", ":")))
            report = score_qa_capture(
                suite=self.suite,
                task_id=task["id"],
                capture_path=capture,
                provider=PROVIDER,
                model=MODEL,
            )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["score"]["earned"], report["score"]["possible"])
        self.assertEqual(report["score"]["percent"], 100.0)
        self.assertEqual(report["observed"], task["expected"])

    def test_partial_error_is_visible_per_field(self):
        task = self.suite["tasks"][0]
        response = dict(task["expected"])
        response["severity"] = "critical"
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.jsonl"
            write_capture(capture, json.dumps(response))
            report = score_qa_capture(
                suite=self.suite,
                task_id=task["id"],
                capture_path=capture,
                provider=PROVIDER,
                model=MODEL,
            )
        self.assertEqual(report["status"], "FAIL")
        failed = [check for check in report["checks"] if not check["passed"]]
        self.assertEqual([check["path"] for check in failed], ["$.severity"])
        self.assertEqual(report["score"], {"earned": 4, "possible": 5, "percent": 80.0})

    def test_extra_field_loses_structure_point(self):
        task = self.suite["tasks"][0]
        response = {**task["expected"], "explanation": "looks plausible"}
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.jsonl"
            write_capture(capture, json.dumps(response))
            report = score_qa_capture(
                suite=self.suite,
                task_id=task["id"],
                capture_path=capture,
                provider=PROVIDER,
                model=MODEL,
            )
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"][0]["passed"])
        self.assertEqual(report["checks"][0]["kind"], "exact_structure")

    def test_markdown_and_failed_inference_are_scored_not_crashed(self):
        task = self.suite["tasks"][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown_capture = root / "markdown.jsonl"
            write_capture(markdown_capture, "```json\n{}\n```")
            markdown = score_qa_capture(
                suite=self.suite,
                task_id=task["id"],
                capture_path=markdown_capture,
                provider=PROVIDER,
                model=MODEL,
            )
            failed_capture = root / "failed.jsonl"
            write_capture(failed_capture, "", complete=False)
            failed = score_qa_capture(
                suite=self.suite,
                task_id=task["id"],
                capture_path=failed_capture,
                provider=PROVIDER,
                model=MODEL,
            )
        self.assertEqual(markdown["status"], "INVALID_RESPONSE")
        self.assertIn("strict JSON", markdown["parse_error"])
        self.assertEqual(failed["status"], "INFERENCE_FAILED")
        self.assertEqual(failed["score"]["percent"], 0.0)

    def test_all_five_task_reports_aggregate_deterministically(self):
        reports = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for task in self.suite["tasks"]:
                capture = root / f"{task['id']}.jsonl"
                write_capture(capture, json.dumps(task["expected"], separators=(",", ":")))
                reports.append(
                    score_qa_capture(
                        suite=self.suite,
                        task_id=task["id"],
                        capture_path=capture,
                        provider=PROVIDER,
                        model=MODEL,
                    )
                )
        summary = summarize_qa_reports(
            suite=self.suite,
            reports=reports,
            provider=PROVIDER,
            model=MODEL,
        )
        self.assertEqual(summary["status"], "COMPLETE")
        self.assertEqual(summary["tasks_total"], 5)
        self.assertEqual(summary["tasks_passed"], 5)
        self.assertEqual(summary["score"]["percent"], 100.0)
        self.assertEqual(set(summary["categories"]), {
            "bug_triage", "test_design", "api_testing", "sql", "log_analysis"
        })

    def test_summary_rejects_missing_and_duplicate_reports(self):
        task = self.suite["tasks"][0]
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.jsonl"
            write_capture(capture, json.dumps(task["expected"]))
            report = score_qa_capture(
                suite=self.suite,
                task_id=task["id"],
                capture_path=capture,
                provider=PROVIDER,
                model=MODEL,
            )
        with self.assertRaisesRegex(QABenchmarkError, "missing QA task reports"):
            summarize_qa_reports(
                suite=self.suite,
                reports=[report],
                provider=PROVIDER,
                model=MODEL,
            )
        with self.assertRaisesRegex(QABenchmarkError, "duplicate QA task report"):
            summarize_qa_reports(
                suite={**self.suite, "tasks": [task]},
                reports=[report, report],
                provider=PROVIDER,
                model=MODEL,
            )

    def test_cli_prepare_score_and_summarize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = self.suite["tasks"][0]
            request = root / "request.json"
            capture = root / "capture.jsonl"
            report = root / "reports" / f"{task['id']}.json"
            write_capture(capture, json.dumps(task["expected"]))

            with redirect_stdout(StringIO()):
                self.assertEqual(main([
                    "prepare", "--suite", str(SUITE_PATH), "--task-id", task["id"],
                    "--model", MODEL, "--output", str(request)
                ]), 0)
                self.assertEqual(main([
                    "score", "--suite", str(SUITE_PATH), "--task-id", task["id"],
                    "--capture", str(capture), "--provider", PROVIDER,
                    "--model", MODEL, "--report", str(report)
                ]), 0)
            self.assertEqual(json.loads(request.read_text())["model"], MODEL)
            self.assertEqual(json.loads(report.read_text())["status"], "PASS")

            with redirect_stderr(StringIO()):
                self.assertEqual(main([
                    "summarize", "--suite", str(SUITE_PATH),
                    "--reports-dir", str(report.parent), "--provider", PROVIDER,
                    "--model", MODEL, "--report", str(root / "summary.json")
                ]), 2)


if __name__ == "__main__":
    unittest.main()
