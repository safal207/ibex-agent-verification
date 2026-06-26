import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ibex_agent_verification.cerebras_runner import (
    CerebrasRunnerBlocked,
    CerebrasRunnerError,
    capture_cerebras_stream,
    run_cerebras_inference,
)
from ibex_agent_verification.cli import main
from ibex_agent_verification.evidence import verify_manifest


class FakeChunk:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


class FakeRawResponse:
    status_code = 200
    http_version = "HTTP/2"
    url = "https://api.cerebras.ai/v1/chat/completions"
    retries_taken = 0
    headers = {
        "content-type": "text/event-stream",
        "x-request-id": "request-123",
        "authorization": "must-not-be-captured",
    }

    def parse(self):
        return iter(
            [
                FakeChunk({"choices": [{"delta": {"content": "hello "}}]}),
                FakeChunk(
                    {
                        "choices": [{"delta": {"content": "world"}}],
                        "usage": {
                            "prompt_tokens": 8,
                            "completion_tokens": 20,
                            "total_tokens": 28,
                        },
                    }
                ),
            ]
        )


class FakeErrorResponse:
    status_code = 429
    http_version = "HTTP/2"
    url = "https://api.cerebras.ai/v1/chat/completions"
    headers = {
        "content-type": "application/json",
        "x-request-id": "request-rate-limited",
    }


class FakeStatusError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.response = FakeErrorResponse()


class FakeCreate:
    def __init__(self, owner, *, failure=None):
        self.owner = owner
        self.failure = failure

    def __call__(self, **request):
        self.owner.request = request
        if self.failure is not None:
            raise self.failure
        return FakeRawResponse()


class FakeWithRawResponse:
    def __init__(self, owner, *, failure=None):
        self.create = FakeCreate(owner, failure=failure)


class FakeCompletions:
    def __init__(self, owner, *, failure=None):
        self.with_raw_response = FakeWithRawResponse(owner, failure=failure)


class FakeChat:
    def __init__(self, owner, *, failure=None):
        self.completions = FakeCompletions(owner, failure=failure)


class FakeClient:
    def __init__(self, *, failure=None):
        self.chat = FakeChat(self, failure=failure)
        self.request = None
        self.closed = False

    def close(self):
        self.closed = True


class CerebrasRunnerTests(unittest.TestCase):
    def write_request(self, root: Path) -> Path:
        request = root / "request.json"
        request.write_text(
            json.dumps(
                {
                    "model": "test-model",
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "messages": [{"role": "user", "content": "Say hello"}],
                    "temperature": 0,
                }
            ),
            encoding="utf-8",
        )
        return request

    def test_capture_preserves_stream_and_allowlists_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            client = FakeClient()
            ticks = iter(
                [
                    1_000_000_000,
                    1_050_000_000,
                    1_100_000_000,
                    1_300_000_000,
                    1_500_000_000,
                ]
            )

            result = capture_cerebras_stream(
                request_payload={"model": "test-model", "stream": True},
                capture_path=capture,
                client=client,
                sdk_version="1.67.0",
                timeout_seconds=60.0,
                clock_ns=lambda: next(ticks),
            )
            events = [json.loads(line) for line in capture.read_text().splitlines()]

        self.assertEqual(result["status"], "CAPTURED")
        self.assertEqual(result["chunk_count"], 2)
        self.assertEqual(
            [event["event"] for event in events],
            ["request_start", "response_headers", "chunk", "chunk", "request_end"],
        )
        self.assertEqual(events[1]["status_code"], 200)
        self.assertEqual(events[1]["headers"]["x-request-id"], "request-123")
        self.assertNotIn("authorization", events[1]["headers"])
        self.assertEqual(events[0]["max_retries"], 0)
        self.assertFalse(events[0]["warm_tcp_connection"])

    def test_real_runner_builds_and_verifies_bundle_without_key_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_request(root)
            evidence = root / "bundle"
            factory_args = {}
            client = FakeClient()

            def factory(**kwargs):
                factory_args.update(kwargs)
                return client

            ticks = iter(
                [
                    1_000_000_000,
                    1_050_000_000,
                    1_100_000_000,
                    1_300_000_000,
                    1_500_000_000,
                ]
            )
            manifest = run_cerebras_inference(
                request_path=request,
                evidence_dir=evidence,
                model="test-model",
                project_sha="project-sha",
                environ={
                    "CEREBRAS_API_KEY": "secret-token",
                    "CEREBRAS_BASE_URL": "https://untrusted.example",
                },
                client_factory=factory,
                sdk_version_override="1.67.0",
                clock_ns=lambda: next(ticks),
            )
            verification = verify_manifest(
                evidence_dir=evidence,
                manifest_path=evidence / "manifest.json",
            )
            persisted = json.loads((evidence / "manifest.json").read_text())
            captured = (evidence / "raw" / "capture.jsonl").read_text()
            all_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in evidence.rglob("*")
                if path.is_file()
            )

        self.assertEqual(manifest["result"]["status"], "COMPLETE")
        self.assertEqual(manifest["result"]["output_tokens_per_second"], 50.0)
        self.assertEqual(verification["status"], "VERIFIED")
        self.assertEqual(verification["files_checked"], 3)
        self.assertEqual(factory_args["base_url"], "https://api.cerebras.ai")
        self.assertEqual(factory_args["max_retries"], 0)
        self.assertFalse(factory_args["warm_tcp_connection"])
        self.assertEqual(factory_args["timeout"], 60.0)
        self.assertTrue(client.closed)
        self.assertTrue(persisted["runner"]["ignored_environment_base_url"])
        self.assertEqual(persisted["runner"]["sdk"]["version"], "1.67.0")
        self.assertNotIn("secret-token", captured)
        self.assertNotIn("secret-token", all_text)
        self.assertNotIn("untrusted.example", captured)

    def test_http_failure_still_produces_verified_failure_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_request(root)
            evidence = root / "bundle"
            client = FakeClient(
                failure=FakeStatusError("rate limited for secret-token")
            )
            ticks = iter([1_000_000_000, 1_050_000_000, 1_100_000_000])

            manifest = run_cerebras_inference(
                request_path=request,
                evidence_dir=evidence,
                model="test-model",
                project_sha="project-sha",
                environ={"CEREBRAS_API_KEY": "secret-token"},
                client_factory=lambda **kwargs: client,
                sdk_version_override="1.67.0",
                clock_ns=lambda: next(ticks),
            )
            verification = verify_manifest(
                evidence_dir=evidence,
                manifest_path=evidence / "manifest.json",
            )
            events = [
                json.loads(line)
                for line in (evidence / "raw" / "capture.jsonl")
                .read_text()
                .splitlines()
            ]

        self.assertEqual(manifest["result"]["status"], "REQUEST_FAILED")
        self.assertEqual(manifest["result"]["http_status"], 429)
        self.assertEqual(verification["status"], "VERIFIED")
        self.assertEqual(events[-1]["event"], "request_error")
        self.assertIn("[REDACTED]", events[-1]["error"])
        self.assertNotIn("secret-token", events[-1]["error"])

    def test_missing_key_is_blocked_without_synthetic_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_request(root)
            evidence = root / "bundle"

            with self.assertRaisesRegex(CerebrasRunnerBlocked, "no network request"):
                run_cerebras_inference(
                    request_path=request,
                    evidence_dir=evidence,
                    model="test-model",
                    project_sha="project-sha",
                    environ={},
                )

            self.assertFalse(evidence.exists())

    def test_invalid_timeout_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_request(root)

            with self.assertRaisesRegex(CerebrasRunnerError, "finite positive"):
                run_cerebras_inference(
                    request_path=request,
                    evidence_dir=root / "bundle",
                    model="test-model",
                    project_sha="project-sha",
                    timeout_seconds=float("nan"),
                    environ={"CEREBRAS_API_KEY": "secret-token"},
                )

    def test_cli_returns_blocked_when_key_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_request(root)
            evidence = root / "bundle"

            with patch.dict(os.environ, {}, clear=True), redirect_stderr(StringIO()) as stderr:
                exit_code = main(
                    [
                        "run-cerebras-inference",
                        "--request",
                        str(request),
                        "--evidence-dir",
                        str(evidence),
                        "--model",
                        "test-model",
                        "--project-sha",
                        "project-sha",
                    ]
                )

        self.assertEqual(exit_code, 4)
        self.assertEqual(json.loads(stderr.getvalue())["status"], "BLOCKED")
        self.assertFalse(evidence.exists())


if __name__ == "__main__":
    unittest.main()
