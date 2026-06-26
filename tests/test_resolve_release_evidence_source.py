import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.resolve_release_evidence_source import (
    ReleaseEvidenceSourceError,
    main,
    resolve_release_evidence_source,
)


def make_source(root: Path, relative: str) -> Path:
    source = root / relative
    (source / "bundle").mkdir(parents=True)
    (source / "bundle" / "manifest.json").write_text("{}\n", encoding="utf-8")
    return source


class ResolveReleaseEvidenceSourceTests(unittest.TestCase):
    def test_defaults_to_release_scoped_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_source(root, "docs/evidence/releases/v1.2.3/cerebras-live")

            resolved = resolve_release_evidence_source(
                repository_root=root,
                tag="v1.2.3",
            )

        self.assertEqual(
            resolved.as_posix(),
            "docs/evidence/releases/v1.2.3/cerebras-live",
        )

    def test_explicit_pointer_can_reuse_an_immutable_milestone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_source(root, "docs/evidence/releases/v0.8.0/cerebras-live")
            releases = root / "docs/releases"
            releases.mkdir(parents=True)
            (releases / "v0.8.1.evidence-source").write_text(
                "docs/evidence/releases/v0.8.0/cerebras-live\n",
                encoding="utf-8",
            )

            resolved = resolve_release_evidence_source(
                repository_root=root,
                tag="v0.8.1",
            )

        self.assertEqual(
            resolved.as_posix(),
            "docs/evidence/releases/v0.8.0/cerebras-live",
        )

    def test_pointer_rejects_traversal_absolute_and_multiline_values(self):
        values = ["../secret\n", "/tmp/secret\n", "a\nb\n"]
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                releases = root / "docs/releases"
                releases.mkdir(parents=True)
                (releases / "v1.0.0.evidence-source").write_text(
                    value,
                    encoding="utf-8",
                )
                with self.assertRaises(ReleaseEvidenceSourceError):
                    resolve_release_evidence_source(
                        repository_root=root,
                        tag="v1.0.0",
                    )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_symlinked_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = make_source(root, "real/evidence")
            releases = root / "docs/releases"
            releases.mkdir(parents=True)
            link = root / "docs/evidence/releases/v1.0.0/cerebras-live"
            link.parent.mkdir(parents=True)
            link.symlink_to(real, target_is_directory=True)

            with self.assertRaisesRegex(ReleaseEvidenceSourceError, "symlink"):
                resolve_release_evidence_source(
                    repository_root=root,
                    tag="v1.0.0",
                )

    def test_missing_manifest_and_invalid_tag_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docs/evidence/releases/v1.0.0/cerebras-live"
            source.mkdir(parents=True)
            with self.assertRaisesRegex(ReleaseEvidenceSourceError, "manifest"):
                resolve_release_evidence_source(
                    repository_root=root,
                    tag="v1.0.0",
                )
            with self.assertRaisesRegex(ReleaseEvidenceSourceError, "invalid"):
                resolve_release_evidence_source(
                    repository_root=root,
                    tag="latest",
                )

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_source(root, "docs/evidence/releases/v1.0.0/cerebras-live")
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    main(["--repository-root", str(root), "--tag", "v1.0.0"]),
                    0,
                )
            self.assertEqual(
                stdout.getvalue().strip(),
                "docs/evidence/releases/v1.0.0/cerebras-live",
            )

            with redirect_stderr(StringIO()):
                self.assertEqual(
                    main(["--repository-root", str(root), "--tag", "bad"]),
                    2,
                )


if __name__ == "__main__":
    unittest.main()
