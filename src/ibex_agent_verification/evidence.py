from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EvidenceError(ValueError):
    """Raised when an evidence bundle cannot be described safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_key_value_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        if "=" not in line:
            raise EvidenceError(f"{path}:{line_number}: expected key=value")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise EvidenceError(f"{path}:{line_number}: empty key")
        if key in values:
            raise EvidenceError(f"{path}:{line_number}: duplicate key {key!r}")
        values[key] = value.strip()
    return values


def collect_files(evidence_dir: Path, output: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    output_resolved = output.resolve()
    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file() or path.resolve() == output_resolved:
            continue
        files.append(
            {
                "path": path.relative_to(evidence_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return files


def build_manifest(
    *,
    evidence_dir: Path,
    output: Path,
    project_sha: str,
    ibex_requested_ref: str,
    ibex_resolved_sha: str,
    ibex_config: str,
    timing_exit_code: int,
    tool_versions_file: Path,
    commands_file: Path,
) -> dict[str, Any]:
    if not evidence_dir.is_dir():
        raise EvidenceError(f"evidence directory does not exist: {evidence_dir}")
    if not tool_versions_file.is_file():
        raise EvidenceError(f"tool versions file does not exist: {tool_versions_file}")
    if not commands_file.is_file():
        raise EvidenceError(f"commands file does not exist: {commands_file}")
    if timing_exit_code not in {0, 1}:
        raise EvidenceError("timing analyzer exit code must be 0 or 1")

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": {
            "repository": "safal207/ibex-agent-verification",
            "commit": project_sha,
        },
        "dut": {
            "repository": "lowRISC/ibex",
            "requested_ref": ibex_requested_ref,
            "resolved_commit": ibex_resolved_sha,
            "configuration": ibex_config,
            "simulator": "verilator",
            "program": "examples/sw/simple_system/hello_test/hello_test.elf",
        },
        "result": {
            "simulation_exit_code": 0,
            "trace_parse_status": "PARSED",
            "timing_analyzer_exit_code": timing_exit_code,
            "timing_anomaly_detected": timing_exit_code == 1,
        },
        "tool_versions": parse_key_value_file(tool_versions_file),
        "commands_file": commands_file.relative_to(evidence_dir).as_posix(),
        "files": collect_files(evidence_dir, output),
    }


def write_manifest(**kwargs: Any) -> dict[str, Any]:
    output = Path(kwargs["output"])
    manifest = build_manifest(**kwargs)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an Ibex evidence manifest")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-sha", required=True)
    parser.add_argument("--ibex-requested-ref", required=True)
    parser.add_argument("--ibex-resolved-sha", required=True)
    parser.add_argument("--ibex-config", required=True)
    parser.add_argument("--timing-exit-code", type=int, required=True)
    parser.add_argument("--tool-versions-file", type=Path, required=True)
    parser.add_argument("--commands-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = write_manifest(
            evidence_dir=args.evidence_dir,
            output=args.output,
            project_sha=args.project_sha,
            ibex_requested_ref=args.ibex_requested_ref,
            ibex_resolved_sha=args.ibex_resolved_sha,
            ibex_config=args.ibex_config,
            timing_exit_code=args.timing_exit_code,
            tool_versions_file=args.tool_versions_file,
            commands_file=args.commands_file,
        )
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "INVALID_EVIDENCE", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"status": "MANIFEST_WRITTEN", "files": len(manifest["files"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
