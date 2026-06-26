#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

from ibex_agent_verification.evidence import verify_manifest
from scripts.resolve_release_evidence_source import resolve_release_evidence_source


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _resolve_build_source(source: Path, repository_root: Path) -> Path:
    source = source.resolve()
    repository_root = repository_root.resolve()
    manifest = source / "bundle" / "manifest.json"
    if manifest.is_file():
        return source

    try:
        relative = source.relative_to(repository_root)
    except ValueError as error:
        raise SystemExit(
            f"release evidence source is outside the repository: {source}"
        ) from error

    if len(relative.parts) < 2 or relative.name != "cerebras-live":
        raise SystemExit(f"cannot infer release tag from evidence source: {relative}")
    tag = relative.parent.name
    resolved_relative = resolve_release_evidence_source(
        repository_root=repository_root,
        tag=tag,
    )
    resolved = repository_root / resolved_relative
    if resolved.resolve() == source:
        raise SystemExit(
            f"release evidence source lacks bundle/manifest.json: {relative}"
        )
    return resolved


def build_asset(
    source: Path,
    output: Path,
    *,
    repository_root: Path = _REPOSITORY_ROOT,
) -> str:
    source = _resolve_build_source(source, repository_root)
    bundle = source / "bundle"
    result = verify_manifest(evidence_dir=bundle, manifest_path=bundle / "manifest.json")
    if result["status"] != "VERIFIED":
        raise SystemExit(f"evidence verification failed: {result}")

    output.parent.mkdir(parents=True, exist_ok=True)
    files = [path for path in sorted(source.rglob("*")) if path.is_file()]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(f"cerebras-live-evidence/{relative}")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"source={source}")
    print(f"asset={output}")
    print(f"sha256={digest}")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_asset(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
