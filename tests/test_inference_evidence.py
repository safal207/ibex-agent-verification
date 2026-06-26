import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.inference_evidence import (
    InferenceEvidenceError,
    analyze_capture,
    build_inference_bundle,
    load_capture,
)


class InferenceEvidenceTests(unittest.TestCase):
    def events(self):
        return [
            {"event": "request_start", "monotonic_ns": 1_000_000_000},
            {
                "event": "response_headers",
                "monotonic_ns": 1_050_000_000,
                "status_code": 200,
            },
            {
                "event": "chunk",
                "monotonic_ns": 1_100_000_000,
                "payload": {"choices": [{"delta": {"content": "hello "}}]},
            },
            {
                "event": "chunk",
                "monotonic_ns": 1_300_000_000,
                "payload": {
                    "choices": [{"delta": {"content": "world"}}],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 20,
                        "total_tokens": 28,
                    },
                },
            },
            {"event": "request_end", "monotonic_ns": 1_500_000_000},
        ]

    def test_computes_only_provider_reported_token_throughput(self):
        result = analyze_capture(self.events(), provider="cerebras", model="test-model")

        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["timing"]["time_to_first_output_ms"], 100.0)
        self.assertEqual(result["timing"]["duration_ms"], 500.0)
        self.assertEqual(result["throughput"]["output_tokens_per_second"], 50.0)
        self.assertEqual(result["throughput"]["source"], "provider_usage")
        self.assertFalse(result["throughput"]["estimated"])
        self.assertEqual(result["output"]["text_characters"], 11)

    def test_missing_usage_does_not_invent_tokens_per_second(self):
        events = self.events()
        events[3]["payload"].pop("usage")

        result = analyze_capture(events, provider="cerebras", model="test-model")

        self.assertIsNone(result["throughput"]["output_tokens_per_second"])
        self.assertIsNone(result["throughput"]["source"])
        self.assertFalse(result["throughput"]["estimated"])

    def test_rejects_non_monotonic_capture(self):
        events = self.events()
        events[2]["monotonic_ns"] = 1

        with self.assertRaisesRegex(InferenceEvidenceError, "non-decreasing"):
            analyze_capture(events, provider="cerebras", model="test-model")

    def test_request_error_is_preserved(self):
        events = [
            {"event": "request_start", "monotonic_ns": 10},
            {
                "event": "request_error",
                "monotonic_ns": 20,
                "error": "timeout",
            },
        ]

        result = analyze_capture(events, provider="cerebras", model="test-model")

        self.assertEqual(result["status"], "REQUEST_FAILED")
        self.assertEqual(result["error"], "timeout")
        self.assertIsNone(result["http_status"])

    def test_builds_bundle_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "model": "test-model",
                        "messages": [{"role": "user", "content": "hi"}],
                    }
                ),
                encoding="utf-8",
            )
            capture = root / "capture.jsonl"
            capture.write_text(
                "\n".join(json.dumps(event) for event in self.events()) + "\n",
                encoding="utf-8",
            )
            evidence = root / "bundle"

            manifest = build_inference_bundle(
                capture_path=capture,
                request_path=request,
                evidence_dir=evidence,
                provider="cerebras",
                model="test-model",
                project_sha="abc123",
            )

            paths = [entry["path"] for entry in manifest["files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertEqual(
                paths,
                ["analysis.json", "raw/capture.jsonl", "raw/request.json"],
            )
            self.assertTrue((evidence / "manifest.json").is_file())
            self.assertEqual(manifest["result"]["status"], "COMPLETE")

    def test_rejects_api_key_in_request_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(json.dumps({"api_key": "secret"}), encoding="utf-8")
            capture = root / "capture.jsonl"
            capture.write_text(
                "\n".join(json.dumps(event) for event in self.events()) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InferenceEvidenceError, "must not contain"):
                build_inference_bundle(
                    capture_path=capture,
                    request_path=request,
                    evidence_dir=root / "bundle",
                    provider="cerebras",
                    model="test-model",
                    project_sha="abc123",
                )

    def test_load_capture_reports_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            path.write_text("{}\nnot-json\n", encoding="utf-8")

            with self.assertRaisesRegex(InferenceEvidenceError, ":2: invalid JSON"):
                load_capture(path)


if __name__ == "__main__":
    unittest.main()
