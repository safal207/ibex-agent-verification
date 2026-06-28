import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.github_release_production_source import (
    GitHubReleaseProductionError,
    build_production_source,
    observe_release,
)
from scripts.production_transition_source import validate_production_transition_source


REPOSITORY = "safal207/ibex-agent-verification"
REPOSITORY_ID = 1278529886
COMMIT = "a" * 40
PROMOTION_WORKFLOW = ".github/workflows/ibex-evidence-promotion.yml"
PROMOTION_RUN_ID = 111111111
PROMOTION_RUN_ATTEMPT = 1
DEPLOYMENT_WORKFLOW = ".github/workflows/github-release-production-deployment.yml"
DEPLOYMENT_RUN_ID = 222222222
DEPLOYMENT_RUN_ATTEMPT = 2
TAG = f"ibex-evidence-{COMMIT}"
ASSET_NAME = f"proofqa-transition-source-{COMMIT}.zip"
RELEASE_ID = 333333333
ASSET_ID = 444444444
PROMOTION_DESTINATION = (
    f"github-actions:repository-id:{REPOSITORY_ID}:environment:ibex-evidence-release"
)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def source_payloads():
    release_id = "ibex-evidence-aaaaaaaaaaaa-111111111-1"
    transition_id = "ibex/evidence-promotion/aaaaaaaaaaaa/111111111/1"
    destination = {
        "environment": "ibex-evidence-release",
        "identity": PROMOTION_DESTINATION,
    }
    deployment = {
        "workflow": PROMOTION_WORKFLOW,
        "run_id": PROMOTION_RUN_ID,
        "run_attempt": PROMOTION_RUN_ATTEMPT,
        "event": "workflow_run",
        "branch": "main",
    }
    subject_digest = "sha256:" + "b" * 64
    common = {
        "schema_version": 1,
        "transition_id": transition_id,
        "repository": REPOSITORY,
        "source_commit": COMMIT,
        "release_id": release_id,
        "destination": destination,
    }
    claim = (
        "Fixture proves a repository-bound evidence promotion. It is not a production "
        "deployment claim."
    )
    return {
        "source-provenance.json": {
            "schema_version": 1,
            "kind": "production-transition-source",
            "repository": REPOSITORY,
            "source_commit": COMMIT,
            "deployment": deployment,
            "destination": destination,
            "release": {
                "release_id": release_id,
                "subject_digest": subject_digest,
            },
            "claim_boundary": claim,
        },
        "transition-report.json": {
            "schema_version": 1,
            "transition_id": transition_id,
            "status": "VERIFIED",
            "phase": "REFLECT",
            "next_phase": "CONTINUE",
            "issues": [],
            "axes": {
                "time": {"status": "PASS"},
                "intention": {"status": "PASS"},
                "space": {"status": "PASS"},
            },
            "evidence": {
                "intent_ref": "manifest:evidence/intent.json",
                "action_ref": "manifest:evidence/action.json",
                "result_ref": "manifest:evidence/result.json",
                "verification_ref": "manifest:evidence/verification.json",
            },
            "claim_boundary": claim,
        },
        "evidence/intent.json": {
            **common,
            "kind": "production-transition-intent",
            "statement": "Promote exact Ibex evidence into the release environment.",
        },
        "evidence/action.json": {
            **common,
            "kind": "production-transition-action",
            "deployment": {
                "workflow": PROMOTION_WORKFLOW,
                "run_id": PROMOTION_RUN_ID,
                "run_attempt": PROMOTION_RUN_ATTEMPT,
            },
            "subject_digest": subject_digest,
            "status": "COMPLETED",
        },
        "evidence/result.json": {
            **common,
            "kind": "production-transition-result",
            "deployment_id": "github-actions/run/111111111/attempt/1",
            "subject_digest": subject_digest,
            "status": "SUCCEEDED",
        },
        "evidence/verification.json": {
            **common,
            "kind": "production-transition-verification",
            "subject_digest": subject_digest,
            "observed_destination": destination,
            "status": "VERIFIED",
            "checks": ["fixture source validated"],
        },
    }


def create_source_archive(path: Path):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for relative, payload in sorted(source_payloads().items()):
            zipped.writestr(
                relative,
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
            )


def selection_for(archive: Path):
    return {
        "schema_version": 1,
        "kind": "trusted-transition-artifact-selection",
        "status": "SELECTED",
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "head_repository_id": REPOSITORY_ID,
        "run_id": PROMOTION_RUN_ID,
        "run_attempt": PROMOTION_RUN_ATTEMPT,
        "workflow": PROMOTION_WORKFLOW,
        "head_branch": "main",
        "head_sha": COMMIT,
        "artifact": {
            "id": 555555555,
            "name": f"proofqa-transition-source-{COMMIT}",
            "size_bytes": archive.stat().st_size,
            "digest": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
            "url": (
                "https://api.github.com/repos/"
                f"{REPOSITORY}/actions/artifacts/555555555"
            ),
            "archive_download_url": (
                "https://api.github.com/repos/"
                f"{REPOSITORY}/actions/artifacts/555555555/zip"
            ),
        },
    }


def release_for(asset: Path, **overrides):
    asset_digest = "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()
    release = {
        "id": RELEASE_ID,
        "tag_name": TAG,
        "target_commitish": COMMIT,
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/{REPOSITORY}/releases/tag/{TAG}",
        "url": f"https://api.github.com/repos/{REPOSITORY}/releases/{RELEASE_ID}",
        "assets": [
            {
                "id": ASSET_ID,
                "name": ASSET_NAME,
                "state": "uploaded",
                "size": asset.stat().st_size,
                "content_type": "application/zip",
                "digest": asset_digest,
                "url": (
                    "https://api.github.com/repos/"
                    f"{REPOSITORY}/releases/assets/{ASSET_ID}"
                ),
                "browser_download_url": (
                    f"https://github.com/{REPOSITORY}/releases/download/"
                    f"{TAG}/{ASSET_NAME}"
                ),
            }
        ],
    }
    release.update(overrides)
    return release


def build(root: Path, *, release_mutator=None, deployed_bytes_mutator=None, selection_mutator=None):
    source_download = root / "source-download"
    source_download.mkdir()
    source_archive = source_download / "source.zip"
    create_source_archive(source_archive)
    selection = selection_for(source_archive)
    if selection_mutator:
        selection_mutator(selection)

    release_download = root / "release-download"
    release_download.mkdir()
    deployed_asset = release_download / ASSET_NAME
    deployed_asset.write_bytes(source_archive.read_bytes())
    if deployed_bytes_mutator:
        deployed_bytes_mutator(deployed_asset)
    release = release_for(deployed_asset)
    if release_mutator:
        release_mutator(release)

    result = build_production_source(
        source_download_dir=source_download,
        source_selection=selection,
        source_extracted_dir=root / "source-extracted",
        release=release,
        release_download_dir=release_download,
        output_dir=root / "production-source",
        expected_repository=REPOSITORY,
        expected_repository_id=REPOSITORY_ID,
        expected_commit=COMMIT,
        expected_source_workflow=PROMOTION_WORKFLOW,
        expected_source_run_id=PROMOTION_RUN_ID,
        expected_source_run_attempt=PROMOTION_RUN_ATTEMPT,
        expected_release_tag=TAG,
        expected_deployment_workflow=DEPLOYMENT_WORKFLOW,
        deployment_run_id=DEPLOYMENT_RUN_ID,
        deployment_run_attempt=DEPLOYMENT_RUN_ATTEMPT,
    )
    return result, root / "production-source", release


class GitHubReleaseProductionSourceTests(unittest.TestCase):
    def test_live_release_builds_valid_production_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, source, _ = build(root)
            destination_id = result["observation"]["destination_id"]

            validation = validate_production_transition_source(
                source_dir=source,
                expected_repository=REPOSITORY,
                expected_commit=COMMIT,
                expected_workflow=DEPLOYMENT_WORKFLOW,
                expected_run_id=DEPLOYMENT_RUN_ID,
                expected_run_attempt=DEPLOYMENT_RUN_ATTEMPT,
                expected_event="workflow_run",
                expected_branch="main",
                expected_environment="ibex-customer-release",
                expected_destination_id=destination_id,
            )

            self.assertEqual(result["status"], "BUILT")
            self.assertEqual(validation["status"], "VALIDATED")
            self.assertEqual(result["source_extraction"]["files_checked"], 6)
            self.assertEqual(result["source_validation"]["status"], "VALIDATED")
            self.assertEqual(result["observation"]["status"], "OBSERVED")
            self.assertIn(f"release-id:{RELEASE_ID}", destination_id)
            self.assertIn(f"asset-id:{ASSET_ID}", destination_id)
            self.assertIn("not a physical production execution claim", result["production_source"]["claim_boundary"])

    def test_observe_release_binds_live_identity_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / ASSET_NAME
            asset.write_bytes(b"release bytes")
            expected_digest = "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()
            observation = observe_release(
                release=release_for(asset),
                expected_repository=REPOSITORY,
                expected_repository_id=REPOSITORY_ID,
                expected_commit=COMMIT,
                expected_tag=TAG,
                expected_asset_name=ASSET_NAME,
                expected_asset_digest=expected_digest,
                downloaded_asset=asset,
            )
            self.assertEqual(observation["asset"]["downloaded_digest"], expected_digest)
            self.assertEqual(observation["release"]["target_commitish"], COMMIT)

    def test_wrong_release_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                GitHubReleaseProductionError, "release target commit mismatch"
            ):
                build(
                    Path(directory),
                    release_mutator=lambda value: value.update(
                        {"target_commitish": "b" * 40}
                    ),
                )

    def test_draft_release_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                GitHubReleaseProductionError, "published, non-draft"
            ):
                build(
                    Path(directory),
                    release_mutator=lambda value: value.update({"draft": True}),
                )

    def test_extra_release_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            def mutate(value):
                value["assets"].append(dict(value["assets"][0], id=999999999, name="extra.zip"))

            with self.assertRaisesRegex(
                GitHubReleaseProductionError, "exactly one immutable source asset"
            ):
                build(Path(directory), release_mutator=mutate)

    def test_live_download_byte_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            def mutate(asset):
                asset.write_bytes(asset.read_bytes() + b"tamper")

            def restore_api_digest(value):
                # API metadata claims the original source digest, while live bytes differ.
                original = Path(directory) / "source-download" / "source.zip"
                value["assets"][0]["digest"] = (
                    "sha256:" + hashlib.sha256(original.read_bytes()).hexdigest()
                )
                value["assets"][0]["size"] = original.stat().st_size

            with self.assertRaisesRegex(
                GitHubReleaseProductionError,
                "downloaded asset size mismatch|downloaded release asset digest mismatch",
            ):
                build(
                    Path(directory),
                    deployed_bytes_mutator=mutate,
                    release_mutator=restore_api_digest,
                )

    def test_foreign_release_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                GitHubReleaseProductionError, "release API URL mismatch"
            ):
                build(
                    Path(directory),
                    release_mutator=lambda value: value.update(
                        {"url": "https://api.github.com/repos/foreign/repo/releases/1"}
                    ),
                )

    def test_foreign_source_workflow_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                GitHubReleaseProductionError, "source selection workflow mismatch"
            ):
                build(
                    Path(directory),
                    selection_mutator=lambda value: value.update(
                        {"workflow": ".github/workflows/foreign.yml"}
                    ),
                )

    def test_release_api_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            def mutate(value):
                value["assets"][0]["digest"] = "sha256:" + "0" * 64

            with self.assertRaisesRegex(
                GitHubReleaseProductionError, "release API digest mismatch"
            ):
                build(Path(directory), release_mutator=mutate)


if __name__ == "__main__":
    unittest.main()
