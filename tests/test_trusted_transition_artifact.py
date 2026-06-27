import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.trusted_transition_artifact import (
    TrustedTransitionArtifactError,
    extract_artifact,
    select_artifact,
)
from scripts.trusted_transition_reference_source import build_reference_source


REPOSITORY = "safal207/ibex-agent-verification"
REPOSITORY_ID = 1278529886
COMMIT = "a" * 40
RUN_ID = 123456789
RUN_ATTEMPT = 2
WORKFLOW = ".github/workflows/proofqa-action.yml"
ARTIFACT_NAME = f"proofqa-transition-source-{COMMIT}"
ARTIFACT_ID = 987654321


def artifact_payload(*, digest_value: str = "sha256:" + "b" * 64):
    api_prefix = (
        f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}"
    )
    return {
        "total_count": 1,
        "artifacts": [
            {
                "id": ARTIFACT_ID,
                "name": ARTIFACT_NAME,
                "size_in_bytes": 4096,
                "url": api_prefix,
                "archive_download_url": f"{api_prefix}/zip",
                "expired": False,
                "digest": digest_value,
                "workflow_run": {
                    "id": RUN_ID,
                    "repository_id": REPOSITORY_ID,
                    "head_repository_id": REPOSITORY_ID,
                    "head_branch": "main",
                    "head_sha": COMMIT,
                },
            }
        ],
    }


def select(payload=None):
    return select_artifact(
        api_payload=artifact_payload() if payload is None else payload,
        expected_repository=REPOSITORY,
        expected_repository_id=REPOSITORY_ID,
        expected_head_repository_id=REPOSITORY_ID,
        expected_run_id=RUN_ID,
        expected_run_attempt=RUN_ATTEMPT,
        expected_workflow=WORKFLOW,
        expected_head_branch="main",
        expected_head_sha=COMMIT,
        expected_name=ARTIFACT_NAME,
    )


def build_source(root: Path) -> Path:
    root.mkdir(parents=True)
    subject = root / "subject.json"
    subject.write_text('{"status":"PASS"}\n', encoding="utf-8")
    source = root / "source"
    result = build_reference_source(
        output_dir=source,
        repository_name=REPOSITORY,
        source_commit=COMMIT,
        workflow_path=WORKFLOW,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        event="push",
        branch="main",
        subject_path=subject,
    )
    assert result["status"] == "BUILT"
    return source


def write_zip(source: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(source).as_posix())


def selection_for_archive(archive: Path):
    payload = artifact_payload(
        digest_value="sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    return select(payload)


class TrustedTransitionArtifactTests(unittest.TestCase):
    def test_reference_source_is_deterministic_and_honest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = build_source(root / "first")
            second = build_source(root / "second")

            first_files = {
                path.relative_to(first).as_posix(): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second).as_posix(): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }
            provenance = json.loads(
                (first / "source-provenance.json").read_text(encoding="utf-8")
            )

            self.assertEqual(first_files, second_files)
            self.assertEqual(len(first_files), 6)
            self.assertEqual(provenance["deployment"]["run_id"], RUN_ID)
            self.assertEqual(provenance["deployment"]["run_attempt"], RUN_ATTEMPT)
            self.assertIn(
                "not a production deployment claim",
                provenance["claim_boundary"],
            )

    def test_exact_artifact_is_selected(self):
        result = select()

        self.assertEqual(result["status"], "SELECTED")
        self.assertEqual(result["run_id"], RUN_ID)
        self.assertEqual(result["run_attempt"], RUN_ATTEMPT)
        self.assertEqual(result["artifact"]["id"], ARTIFACT_ID)
        self.assertEqual(result["artifact"]["name"], ARTIFACT_NAME)

    def test_missing_or_ambiguous_artifact_is_rejected(self):
        for payload in (
            {"total_count": 0, "artifacts": []},
            {
                "total_count": 2,
                "artifacts": artifact_payload()["artifacts"] * 2,
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(
                    TrustedTransitionArtifactError,
                    "exactly one artifact",
                ):
                    select(payload)

    def test_expired_artifact_is_rejected(self):
        payload = artifact_payload()
        payload["artifacts"][0]["expired"] = True

        with self.assertRaisesRegex(
            TrustedTransitionArtifactError,
            "not be expired",
        ):
            select(payload)

    def test_foreign_head_sha_is_rejected(self):
        payload = artifact_payload()
        payload["artifacts"][0]["workflow_run"]["head_sha"] = "c" * 40

        with self.assertRaisesRegex(
            TrustedTransitionArtifactError,
            "workflow_run.head_sha mismatch",
        ):
            select(payload)

    def test_exact_archive_is_extracted_and_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = build_source(root / "source-root")
            download = root / "download"
            download.mkdir()
            archive = download / "artifact.zip"
            write_zip(source, archive)
            selection = selection_for_archive(archive)

            result = extract_artifact(
                download_dir=download,
                selection=selection,
                output_dir=root / "extracted",
            )

            self.assertEqual(result["status"], "EXTRACTED")
            self.assertEqual(result["files_checked"], 6)
            self.assertEqual(
                {item["path"] for item in result["files"]},
                {
                    "source-provenance.json",
                    "transition-report.json",
                    "evidence/intent.json",
                    "evidence/action.json",
                    "evidence/result.json",
                    "evidence/verification.json",
                },
            )

    def test_archive_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = build_source(root / "source-root")
            download = root / "download"
            download.mkdir()
            archive = download / "artifact.zip"
            write_zip(source, archive)
            selection = select()

            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "digest mismatch",
            ):
                extract_artifact(
                    download_dir=download,
                    selection=selection,
                    output_dir=root / "extracted",
                )

    def test_traversal_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            download = root / "download"
            download.mkdir()
            archive = download / "artifact.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("../escape.json", "{}")
            selection = selection_for_archive(archive)

            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "not canonical",
            ):
                extract_artifact(
                    download_dir=download,
                    selection=selection,
                    output_dir=root / "extracted",
                )

    def test_symbolic_link_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            download = root / "download"
            download.mkdir()
            archive = download / "artifact.zip"
            info = zipfile.ZipInfo("source-provenance.json")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(info, "target")
            selection = selection_for_archive(archive)

            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "symbolic link",
            ):
                extract_artifact(
                    download_dir=download,
                    selection=selection,
                    output_dir=root / "extracted",
                )

    def test_case_colliding_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            download = root / "download"
            download.mkdir()
            archive = download / "artifact.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("evidence/intent.json", "{}")
                zipped.writestr("Evidence/intent.json", "{}")
            selection = selection_for_archive(archive)

            with self.assertRaisesRegex(
                TrustedTransitionArtifactError,
                "case-colliding",
            ):
                extract_artifact(
                    download_dir=download,
                    selection=selection,
                    output_dir=root / "extracted",
                )


if __name__ == "__main__":
    unittest.main()
