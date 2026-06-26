import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from ibex_agent_verification.cli import main
from ibex_agent_verification.evidence import verify_manifest
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

    def write_inputs(self, root: Path) -> tuple[Path, Path]:
        request = root / "request.json"
        request.write_text(
            json.dumps(
                {
                    "model": "test-model",
                    "stream": True,
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
        return request, capture

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

    def test_builds_and_independently_verifies_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, capture = self.write_inputs(root)
            evidence = root / "bundle"

            manifest = build_inference_bundle(
                capture_path=capture,
                request_path=request,
                evidence_dir=evidence,
                provider="cerebras",
                model="test-model",
                project_sha="abc123",
            )
            verification = verify_manifest(
                evidence_dir=evidence,
                manifest_path=evidence / "manifest.json",
            )

            paths = [entry["path"] for entry in manifest["files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertEqual(
                paths,
                ["analysis.json", "raw/capture.jsonl", "raw/request.json"],
            )
            self.assertEqual(manifest["result"]["status"], "COMPLETE")
            self.assertEqual(verification["status"], "VERIFIED")
            self.assertEqual(verification["files_checked"], 3)

    def test_cli_builds_bundle_and_writes_external_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, capture = self.write_inputs(root)
            evidence = root / "bundle"
            report = root / "cli-report.json"

            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "build-inference-evidence",
                        "--request",
                        str(request),
                        "--capture",
                        str(capture),
                        "--evidence-dir",
                        str(evidence),
                        "--provider",
                        "cerebras",
                        "--model",
                        "test-model",
                        "--project-sha",
                        "abc123",
                        "--report",
                        str(report),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(report.read_text())["result"]["status"], "COMPLETE")
            self.assertEqual(
                verify_manifest(
                    evidence_dir=evidence,
                    manifest_path=evidence / "manifest.json",
                )["status"],
                "VERIFIED",
            )

    def test_rejects_nested_api_key_in_request_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "model": "test-model",
                        "stream": True,
                        "metadata": {"api_key": "secret"},
                    }
                ),
                encoding="utf-8",
            )
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

    def test_rejects_request_model_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(
                json.dumps({"model": "different-model", "stream": True}),
                encoding="utf-8",
            )
            capture = root / "capture.jsonl"
            capture.write_text(
                "\n".join(json.dumps(event) for event in self.events()) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InferenceEvidenceError, "must exactly match"):
                build_inference_bundle(
                    capture_path=capture,
                    request_path=request,
                    evidence_dir=root / "bundle",
                    provider="cerebras",
                    model="test-model",
                    project_sha="abc123",
                )

    def test_rejects_non_streaming_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(
                json.dumps({"model": "test-model", "stream": False}),
                encoding="utf-8",
            )
            capture = root / "capture.jsonl"
            capture.write_text(
                "\n".join(json.dumps(event) for event in self.events()) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InferenceEvidenceError, "stream must be true"):
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
