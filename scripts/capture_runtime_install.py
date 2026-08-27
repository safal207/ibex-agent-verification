#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    """Write measured installation metadata into a strict JSON receipt."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-filename", required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--python-executable", required=True)
    parser.add_argument("--sys-prefix", required=True)
    parser.add_argument("--sys-base-prefix", required=True)
    parser.add_argument("--isolated", choices=("0", "1"), required=True)
    parser.add_argument("--module-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = {
        "schema_version": 1,
        "status": "INSTALLED",
        "package_name": "ibex-agent-verification",
        "package_version": args.package_version,
        "wheel_filename": args.wheel_filename,
        "wheel_sha256": args.wheel_sha256,
        "python_version": args.python_version,
        "python_executable": args.python_executable,
        "sys_prefix": args.sys_prefix,
        "sys_base_prefix": args.sys_base_prefix,
        "isolated": args.isolated == "1",
        "module_file": args.module_file,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
