#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

from ibex_agent_verification.evidence import verify_manifest


def build_asset(source: Path, output: Path) -> str:
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
