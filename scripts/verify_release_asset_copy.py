#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import BinaryIO


class ReleaseAssetCopyError(ValueError):
    """Raised when release asset copies cannot be compared safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _streams_equal(expected: BinaryIO, actual: BinaryIO) -> bool:
    while True:
        expected_chunk = expected.read(1024 * 1024)
        actual_chunk = actual.read(1024 * 1024)
        if expected_chunk != actual_chunk:
            return False
        if not expected_chunk:
            return True


def verify_release_asset_copy(expected: Path, actual: Path) -> dict[str, object]:
    expected = expected.resolve()
    actual = actual.resolve()

    for label, path in (("expected", expected), ("actual", actual)):
        if not path.is_file():
            raise ReleaseAssetCopyError(f"{label} release asset is not a file: {path}")

    expected_size = expected.stat().st_size
    actual_size = actual.stat().st_size
    expected_sha256 = _sha256(expected)
    actual_sha256 = _sha256(actual)

    with expected.open("rb") as expected_stream, actual.open("rb") as actual_stream:
        bytes_equal = _streams_equal(expected_stream, actual_stream)

    verified = (
        expected_size == actual_size
        and expected_sha256 == actual_sha256
        and bytes_equal
    )
    return {
        "schema_version": 1,
        "status": "VERIFIED" if verified else "INTEGRITY_MISMATCH",
        "expected": {
            "path": str(expected),
            "size_bytes": expected_size,
            "sha256": expected_sha256,
        },
        "actual": {
            "path": str(actual),
            "size_bytes": actual_size,
            "sha256": actual_sha256,
        },
        "bytes_equal": bytes_equal,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that a downloaded GitHub Release asset exactly matches its local source."
    )
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--actual", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = verify_release_asset_copy(args.expected, args.actual)
    except (OSError, ReleaseAssetCopyError) as error:
        print(f"release asset verification error: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
