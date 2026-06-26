import json
import tempfile
import unittest
from pathlib import Path

from ibex_agent_verification.cerebras_runner import (
    CerebrasRunnerError,
    run_cerebras_inference,
)


class CerebrasRunnerPreflightTests(unittest.TestCase):
    def write_request(self, root: Path) -> Path:
        request = root / "request.json"
        request.write_text(
            json.dumps(
                {
                    "model": "test-model",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hello"}],
                }
            ),
            encoding="utf-8",
        )
        return request

    def test_nonempty_evidence_directory_is_rejected_before_client_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_request(root)
            evidence = root / "bundle"
            evidence.mkdir()
            (evidence / "existing.txt").write_text("do not overwrite", encoding="utf-8")
            factory_called = False

            def factory(**kwargs):
                nonlocal factory_called
                factory_called = True
                raise AssertionError("client factory must not be called")

            with self.assertRaisesRegex(CerebrasRunnerError, "empty or absent"):
                run_cerebras_inference(
                    request_path=request,
                    evidence_dir=evidence,
                    model="test-model",
                    project_sha="project-sha",
                    environ={"CEREBRAS_API_KEY": "secret-token"},
                    client_factory=factory,
                )

            self.assertFalse(factory_called)
            self.assertEqual(
                (evidence / "existing.txt").read_text(encoding="utf-8"),
                "do not overwrite",
            )

    def test_empty_project_sha_is_rejected_before_client_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_request(root)
            factory_called = False

            def factory(**kwargs):
                nonlocal factory_called
                factory_called = True
                raise AssertionError("client factory must not be called")

            with self.assertRaisesRegex(CerebrasRunnerError, "project_sha"):
                run_cerebras_inference(
                    request_path=request,
                    evidence_dir=root / "bundle",
                    model="test-model",
                    project_sha="",
                    environ={"CEREBRAS_API_KEY": "secret-token"},
                    client_factory=factory,
                )

            self.assertFalse(factory_called)


if __name__ == "__main__":
    unittest.main()
