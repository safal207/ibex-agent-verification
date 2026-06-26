import unittest

from ibex_agent_verification.qa_benchmark import QABenchmarkError
from ibex_agent_verification.qa_scorecard import build_reliability_scorecard


def report(
    task_id: str,
    *,
    status: str,
    earned: int,
    possible: int = 5,
    inference_status: str | None = "COMPLETE",
    http_status: int | None = 200,
) -> dict:
    payload = {
        "task_id": task_id,
        "status": status,
        "score": {
            "earned": earned,
            "possible": possible,
            "percent": round(earned * 100.0 / possible, 6),
        },
    }
    if inference_status is not None:
        payload["inference_status"] = inference_status
    if http_status is not None:
        payload["http_status"] = http_status
    return payload


class QAScorecardTests(unittest.TestCase):
    def test_mixed_run_separates_all_three_axes(self):
        scorecard = build_reliability_scorecard(
            [
                report("pass", status="PASS", earned=5),
                report("partial", status="FAIL", earned=4),
                report("invalid", status="INVALID_RESPONSE", earned=0),
                report("truncated", status="OUTPUT_TRUNCATED", earned=0),
                report(
                    "quota",
                    status="INFERENCE_FAILED",
                    earned=0,
                    inference_status="REQUEST_FAILED",
                    http_status=429,
                ),
            ]
        )

        self.assertEqual(
            scorecard["end_to_end_score"],
            {
                "earned": 9,
                "possible": 25,
                "percent": 36.0,
                "definition": scorecard["end_to_end_score"]["definition"],
            },
        )
        self.assertEqual(scorecard["answer_correctness"]["earned"], 9)
        self.assertEqual(scorecard["answer_correctness"]["possible"], 10)
        self.assertEqual(scorecard["answer_correctness"]["percent"], 90.0)
        self.assertEqual(scorecard["answer_correctness"]["tasks_evaluated"], 2)

        self.assertEqual(scorecard["completion_reliability"]["completed"], 2)
        self.assertEqual(scorecard["completion_reliability"]["total"], 5)
        self.assertEqual(scorecard["completion_reliability"]["percent"], 40.0)

        provider = scorecard["provider_reliability"]
        self.assertEqual(provider["successful"], 4)
        self.assertEqual(provider["failed"], 1)
        self.assertEqual(provider["unknown"], 0)
        self.assertEqual(provider["observed"], 5)
        self.assertEqual(provider["percent"], 80.0)
        self.assertEqual(provider["failure_classes"], {"http_429": 1})

        self.assertEqual(
            scorecard["outcomes"],
            {
                "pass": 1,
                "fail": 1,
                "invalid_response": 1,
                "output_truncated": 1,
                "inference_failed": 1,
            },
        )

    def test_truncation_is_completion_failure_but_provider_success(self):
        scorecard = build_reliability_scorecard(
            [report("truncated", status="OUTPUT_TRUNCATED", earned=0)]
        )
        self.assertEqual(scorecard["completion_reliability"]["percent"], 0.0)
        self.assertIsNone(scorecard["answer_correctness"]["percent"])
        self.assertEqual(scorecard["provider_reliability"]["percent"], 100.0)
        self.assertEqual(
            scorecard["task_results"][0]["provider_outcome"],
            "success",
        )

    def test_missing_provider_metadata_is_explicitly_unknown(self):
        scorecard = build_reliability_scorecard(
            [
                report(
                    "legacy",
                    status="PASS",
                    earned=5,
                    inference_status=None,
                    http_status=None,
                )
            ]
        )
        provider = scorecard["provider_reliability"]
        self.assertEqual(provider["successful"], 0)
        self.assertEqual(provider["failed"], 0)
        self.assertEqual(provider["unknown"], 1)
        self.assertEqual(provider["observed"], 0)
        self.assertIsNone(provider["percent"])

    def test_transport_failure_has_separate_failure_class(self):
        scorecard = build_reliability_scorecard(
            [
                report(
                    "timeout",
                    status="INFERENCE_FAILED",
                    earned=0,
                    inference_status="REQUEST_FAILED",
                    http_status=None,
                )
            ]
        )
        self.assertEqual(
            scorecard["provider_reliability"]["failure_classes"],
            {"transport_timeout_or_unknown": 1},
        )

    def test_rejects_duplicate_tasks_and_unsupported_statuses(self):
        duplicate = report("same", status="PASS", earned=5)
        with self.assertRaisesRegex(QABenchmarkError, "duplicate QA task report"):
            build_reliability_scorecard([duplicate, duplicate])
        with self.assertRaisesRegex(QABenchmarkError, "unsupported status"):
            build_reliability_scorecard(
                [report("bad", status="MYSTERY", earned=0)]
            )

    def test_requires_non_empty_report_set(self):
        with self.assertRaisesRegex(QABenchmarkError, "at least one"):
            build_reliability_scorecard([])


if __name__ == "__main__":
    unittest.main()
