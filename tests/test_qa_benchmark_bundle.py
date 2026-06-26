import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.evidence import verify_manifest
from ibex_agent_verification.inference_evidence import build_inference_bundle
from ibex_agent_verification.qa_benchmark import (
    build_qa_request,
    load_qa_suite,
    score_qa_capture,
    summarize_qa_reports,
)
from scripts.build_qa_benchmark_bundle import (
    QABenchmarkBundleError,
    build_qa_benchmark_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "benchmarks/qa-engineer-core-v0.1.json"
PROVIDER = "cerebras"
MODEL = "test-model"
PROJECT_SHA = "a" * 40


def write_capture(path: Path, text: str) -> None:
    events = [
        {"event": "request_start", "monotonic_ns": 1},
        {"event": "response_headers", "monotonic_ns": 2, "status_code": 200},
        {
            "event": "chunk",
            "monotonic_ns": 3,
            "payload": {"choices": [{"delta": {"content": text}}]},
        },
        {
            "event": "chunk",
            "monotonic_ns": 4,
            "payload": {
                "choices": [{"delta": {}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        },
        {"event": "request_end", "monotonic_ns": 5},
    ]
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def build_complete_bundle(bundle: Path) -> tuple[dict, list[dict]]:
    suite = load_qa_suite(SUITE_PATH)
    bundle.mkdir(parents=True)
    (bundle / "model-catalog.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": PROVIDER,
                "requested_model": MODEL,
                "requested_model_available": True,
                "model_ids": [MODEL],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    reports = []
    for task in suite["tasks"]:
        task_root = bundle / "tasks" / task["id"]
        task_root.mkdir(parents=True)
        request = task_root / "request.json"
        request.write_text(
            json.dumps(
                build_qa_request(suite=suite, task_id=task["id"], model=MODEL),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        capture = task_root / "capture-source.jsonl"
        write_capture(capture, json.dumps(task["expected"], separators=(",", ":")))
        build_inference_bundle(
            capture_path=capture,
            request_path=request,
            evidence_dir=task_root / "evidence",
            provider=PROVIDER,
            model=MODEL,
            project_sha=PROJECT_SHA,
        )
        capture.unlink()
        verification = verify_manifest(
            evidence_dir=task_root / "evidence",
            manifest_path=task_root / "evidence" / "manifest.json",
        )
        (task_root / "verification.json").write_text(
            json.dumps(verification, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (task_root / "run-report.json").write_text(
            json.dumps({"result": {"status": "COMPLETE"}}, indent=2) + "\n",
            encoding="utf-8",
        )
        score = score_qa_capture(
            suite=suite,
            task_id=task["id"],
            capture_path=task_root / "evidence" / "raw" / "capture.jsonl",
            provider=PROVIDER,
            model=MODEL,
        )
        (task_root / "score.json").write_text(
            json.dumps(score, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        reports.append(score)

    summary = summarize_qa_reports(
        suite=suite,
        reports=reports,
        provider=PROVIDER,
        model=MODEL,
    )
    (bundle / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return suite, reports


class QABenchmarkBundleTests(unittest.TestCase):
    def test_outer_manifest_covers_scores_and_inner_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "qa-benchmark"
            suite, _ = build_complete_bundle(bundle)
            manifest = build_qa_benchmark_manifest(
                bundle_dir=bundle,
                suite_path=SUITE_PATH,
                provider=PROVIDER,
                model=MODEL,
                project_sha=PROJECT_SHA,
            )
            verification = verify_manifest(
                evidence_dir=bundle,
                manifest_path=bundle / "manifest.json",
            )

        self.assertEqual(manifest["result"]["status"], "COMPLETE")
        self.assertEqual(manifest["workload"]["task_count"], len(suite["tasks"]))
        self.assertEqual(manifest["result"]["score"]["percent"], 100.0)
        self.assertEqual(verification["status"], "VERIFIED")
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("summary.json", paths)
        self.assertIn("tasks/bug-triage-idempotency/score.json", paths)
        self.assertIn("tasks/sql-result-paid-orders/evidence/raw/capture.jsonl", paths)

    def test_missing_file_and_wrong_summary_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "missing"
            build_complete_bundle(bundle)
            (bundle / "tasks/bug-triage-idempotency/score.json").unlink()
            with self.assertRaisesRegex(QABenchmarkBundleError, "file set mismatch"):
                build_qa_benchmark_manifest(
                    bundle_dir=bundle,
                    suite_path=SUITE_PATH,
                    provider=PROVIDER,
                    model=MODEL,
                    project_sha=PROJECT_SHA,
                )

        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "identity"
            build_complete_bundle(bundle)
            summary_path = bundle / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["model"] = "other-model"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(QABenchmarkBundleError, "provider/model mismatch"):
                build_qa_benchmark_manifest(
                    bundle_dir=bundle,
                    suite_path=SUITE_PATH,
                    provider=PROVIDER,
                    model=MODEL,
                    project_sha=PROJECT_SHA,
                )

    def test_tampering_after_manifest_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "tamper"
            build_complete_bundle(bundle)
            build_qa_benchmark_manifest(
                bundle_dir=bundle,
                suite_path=SUITE_PATH,
                provider=PROVIDER,
                model=MODEL,
                project_sha=PROJECT_SHA,
            )
            score = bundle / "tasks/logs-duplicate-order/score.json"
            score.write_text(score.read_text(encoding="utf-8") + " ", encoding="utf-8")
            verification = verify_manifest(
                evidence_dir=bundle,
                manifest_path=bundle / "manifest.json",
            )
        self.assertEqual(verification["status"], "INTEGRITY_MISMATCH")
        self.assertEqual(verification["mismatches"][0]["path"], "tasks/logs-duplicate-order/score.json")


if __name__ == "__main__":
    unittest.main()
