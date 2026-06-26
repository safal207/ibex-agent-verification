#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from pathlib import Path


_TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")


class ReleaseEvidenceSourceError(ValueError):
    """Raised when a release evidence source is missing or unsafe."""


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            raise ReleaseEvidenceSourceError(
                f"release evidence path does not exist: {relative.as_posix()}"
            ) from error
        if stat.S_ISLNK(mode):
            raise ReleaseEvidenceSourceError(
                f"release evidence path contains a symlink: {current.relative_to(root)}"
            )


def resolve_release_evidence_source(
    *,
    repository_root: Path,
    tag: str,
    pointer_directory: Path = Path("docs/releases"),
) -> Path:
    repository_root = repository_root.resolve()
    if not repository_root.is_dir():
        raise ReleaseEvidenceSourceError(
            f"repository root is not a directory: {repository_root}"
        )
    if not _TAG_RE.fullmatch(tag):
        raise ReleaseEvidenceSourceError(f"invalid semantic release tag: {tag!r}")

    pointer_relative = pointer_directory / f"{tag}.evidence-source"
    pointer = repository_root / pointer_relative
    default_relative = Path("docs/evidence/releases") / tag / "cerebras-live"

    if pointer.is_file():
        lines = pointer.read_text(encoding="utf-8").splitlines()
        if len(lines) != 1 or not lines[0].strip():
            raise ReleaseEvidenceSourceError(
                f"evidence source pointer must contain exactly one non-empty line: {pointer_relative}"
            )
        source_relative = Path(lines[0].strip())
    else:
        source_relative = default_relative

    if source_relative.is_absolute() or ".." in source_relative.parts:
        raise ReleaseEvidenceSourceError(
            f"evidence source must be repository-relative without '..': {source_relative}"
        )
    if source_relative.as_posix() != str(source_relative).replace("\\", "/"):
        raise ReleaseEvidenceSourceError(
            f"evidence source must use a normalized repository path: {source_relative}"
        )

    _reject_symlink_components(repository_root, source_relative)
    source = repository_root / source_relative
    if not source.is_dir():
        raise ReleaseEvidenceSourceError(
            f"release evidence source is not a directory: {source_relative}"
        )
    if not (source / "bundle" / "manifest.json").is_file():
        raise ReleaseEvidenceSourceError(
            f"release evidence source lacks bundle/manifest.json: {source_relative}"
        )
    return source_relative


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve a safe, explicit repository-relative evidence source for a release."
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--pointer-directory", type=Path, default=Path("docs/releases"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        source = resolve_release_evidence_source(
            repository_root=args.repository_root,
            tag=args.tag,
            pointer_directory=args.pointer_directory,
        )
    except (OSError, UnicodeError, ReleaseEvidenceSourceError) as error:
        print(f"release evidence source error: {error}", file=sys.stderr)
        return 2
    print(source.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
