import hashlib
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.audit_published_release import (
    PublishedReleaseAuditError,
    audit_published_release,
    main,
    release_asset_names,
)


TAG = "v0.8.1"
REPOSITORY = "safal207/ibex-agent-verification"
COMMIT = "d" * 40
WORKFLOW = ".github/workflows/release.yml"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_release(directory: Path, *, unsafe_member: str | None = None) -> None:
    names = release_asset_names(TAG)
    bundle_files = {
        "analysis.json": b"{}\n",
        "raw/request.json": b"{}\n",
        "raw/capture.jsonl": b'{"event":"request_start"}\n',
    }
    manifest = {
        "schema_version": 1,
        "files": [
            {
                "path": path,
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
            for path, payload in sorted(bundle_files.items())
        ],
    }
    zip_files = {
        "cerebras-live-evidence/bundle/manifest.json": (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode(),
        **{
            f"cerebras-live-evidence/bundle/{path}": payload
            for path, payload in bundle_files.items()
        },
        "cerebras-live-evidence/verification.json": b'{"status":"VERIFIED"}\n',
        "cerebras-live-evidence/receipt.json": b"{}\n",
        "cerebras-live-evidence/receipt.md": b"# receipt\n",
    }
    if unsafe_member is not None:
        zip_files[unsafe_member] = b"unsafe\n"

    asset = directory / names["asset"]
    with zipfile.ZipFile(
        asset,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name, payload in sorted(zip_files.items()):
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload, compresslevel=9)

    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    size_bytes = asset.stat().st_size
    (directory / names["checksum"]).write_text(
        f"{digest}  {names['asset']}\n",
        encoding="utf-8",
    )
    provenance = {
        "format": "ibex-agent-verification.release-asset-provenance.v1",
        "release": {
            "commit": COMMIT,
            "repository": REPOSITORY,
            "tag": TAG,
        },
        "subject": {
            "digest": {"sha256": digest},
            "name": names["asset"],
            "size_bytes": size_bytes,
        },
        "builder": {"workflow": WORKFLOW},
    }
    (directory / names["provenance"]).write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / names["attestation"]).write_text(
        json.dumps({"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"})
        + "\n",
        encoding="utf-8",
    )


class PublishedReleaseAuditTests(unittest.TestCase):
    def test_valid_release_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_release(root)

            result = audit_published_release(
                directory=root,
                tag=TAG,
                repository=REPOSITORY,
                commit=COMMIT,
            )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["archive"]["manifest"]["status"], "VERIFIED")
        self.assertEqual(result["archive"]["manifest"]["files_checked"], 3)

    def test_tampered_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_release(root)
            asset = root / release_asset_names(TAG)["asset"]
            asset.write_bytes(asset.read_bytes() + b"tampered")

            with self.assertRaisesRegex(
                PublishedReleaseAuditError,
                "metadata mismatch",
            ):
                audit_published_release(
                    directory=root,
                    tag=TAG,
                    repository=REPOSITORY,
                    commit=COMMIT,
                )

    def test_wrong_commit_in_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_release(root)

            with self.assertRaisesRegex(
                PublishedReleaseAuditError,
                "metadata mismatch",
            ):
                audit_published_release(
                    directory=root,
                    tag=TAG,
                    repository=REPOSITORY,
                    commit="e" * 40,
                )

    def test_unsafe_zip_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_release(root, unsafe_member="../escape.txt")

            with self.assertRaisesRegex(
                PublishedReleaseAuditError,
                "unsafe ZIP member",
            ):
                audit_published_release(
                    directory=root,
                    tag=TAG,
                    repository=REPOSITORY,
                    commit=COMMIT,
                )

    def test_missing_or_unexpected_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_release(root)
            names = release_asset_names(TAG)
            (root / names["attestation"]).unlink()
            with self.assertRaisesRegex(PublishedReleaseAuditError, "missing published"):
                audit_published_release(
                    directory=root,
                    tag=TAG,
                    repository=REPOSITORY,
                    commit=COMMIT,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_release(root)
            (root / "unexpected.txt").write_text("nope\n", encoding="utf-8")
            with self.assertRaisesRegex(PublishedReleaseAuditError, "unexpected files"):
                audit_published_release(
                    directory=root,
                    tag=TAG,
                    repository=REPOSITORY,
                    commit=COMMIT,
                )

    def test_cli_writes_machine_readable_report_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release_dir = root / "release"
            release_dir.mkdir()
            report = root / "audit.json"
            build_release(release_dir)
            args = [
                "--directory",
                str(release_dir),
                "--tag",
                TAG,
                "--repository",
                REPOSITORY,
                "--commit",
                COMMIT,
                "--report",
                str(report),
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), 0)
            self.assertEqual(
                json.loads(report.read_text(encoding="utf-8"))["status"],
                "VERIFIED",
            )

            (release_dir / release_asset_names(TAG)["checksum"]).unlink()
            with redirect_stderr(StringIO()):
                self.assertEqual(main(args), 2)


if __name__ == "__main__":
    unittest.main()
