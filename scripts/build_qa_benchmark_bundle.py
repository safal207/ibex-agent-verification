#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ibex_agent_verification.evidence import collect_files, sha256_file, verify_manifest
from ibex_agent_verification.qa_benchmark import QABenchmarkError, load_qa_suite


class QABenchmarkBundleError(ValueError):
    """Raised when a QA benchmark evidence bundle is incomplete or inconsistent."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise QABenchmarkBundleError(f"{label} must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise QABenchmarkBundleError(f"{path}: invalid {label} JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise QABenchmarkBundleError(f"{label} must be a JSON object: {path}")
    return payload


def _expected_relative_files(suite: dict[str, Any]) -> set[str]:
    expected = {
        "model-catalog.json",
        "summary.json",
    }
    for task in suite["tasks"]:
        prefix = f"tasks/{task['id']}"
        expected.update(
            {
                f"{prefix}/request.json",
                f"{prefix}/run-report.json",
                f"{prefix}/verification.json",
                f"{prefix}/score.json",
                f"{prefix}/evidence/analysis.json",
                f"{prefix}/evidence/manifest.json",
                f"{prefix}/evidence/raw/request.json",
                f"{prefix}/evidence/raw/capture.jsonl",
            }
        )
    return expected


def build_qa_benchmark_manifest(
    *,
    bundle_dir: Path,
    suite_path: Path,
    provider: str,
    model: str,
    project_sha: str,
) -> dict[str, Any]:
    if bundle_dir.is_symlink() or not bundle_dir.is_dir():
        raise QABenchmarkBundleError(
            f"QA benchmark bundle must be a real directory: {bundle_dir}"
        )
    if not provider.strip() or not model.strip() or not project_sha.strip():
        raise QABenchmarkBundleError("provider, model, and project_sha must be non-empty")
    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise QABenchmarkBundleError(f"QA benchmark manifest already exists: {manifest_path}")

    suite = load_qa_suite(suite_path)
    expected = _expected_relative_files(suite)
    observed = {
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file()
    }
    if observed != expected:
        raise QABenchmarkBundleError(
            "QA benchmark bundle file set mismatch; "
            f"missing={sorted(expected - observed)} unexpected={sorted(observed - expected)}"
        )

    summary = _load_object(bundle_dir / "summary.json", label="QA benchmark summary")
    if summary.get("status") != "COMPLETE":
        raise QABenchmarkBundleError("QA benchmark summary status must be COMPLETE")
    if summary.get("suite_id") != suite["suite_id"]:
        raise QABenchmarkBundleError("QA benchmark summary suite_id mismatch")
    if summary.get("provider") != provider or summary.get("model") != model:
        raise QABenchmarkBundleError("QA benchmark summary provider/model mismatch")
    if summary.get("tasks_total") != len(suite["tasks"]):
        raise QABenchmarkBundleError("QA benchmark summary task count mismatch")

    for task in suite["tasks"]:
        root = bundle_dir / "tasks" / task["id"]
        verification = verify_manifest(
            evidence_dir=root / "evidence",
            manifest_path=root / "evidence" / "manifest.json",
        )
        if verification["status"] != "VERIFIED":
            raise QABenchmarkBundleError(
                f"inner inference evidence failed verification for {task['id']}: {verification}"
            )
        score = _load_object(root / "score.json", label="QA task score")
        if score.get("suite_id") != suite["suite_id"] or score.get("task_id") != task["id"]:
            raise QABenchmarkBundleError(f"QA task score identity mismatch: {task['id']}")
        if score.get("provider") != provider or score.get("model") != model:
            raise QABenchmarkBundleError(f"QA task score provider/model mismatch: {task['id']}")

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": {
            "repository": "safal207/ibex-agent-verification",
            "commit": project_sha,
        },
        "workload": {
            "kind": "ai_qa_engineer_verification_suite",
            "provider": provider,
            "model": model,
            "suite_id": suite["suite_id"],
            "suite_sha256": sha256_file(suite_path),
            "task_count": len(suite["tasks"]),
        },
        "result": {
            "status": "COMPLETE",
            "tasks_passed": summary["tasks_passed"],
            "tasks_failed": summary["tasks_failed"],
            "tasks_invalid": summary["tasks_invalid"],
            "score": summary["score"],
        },
        "claim_boundary": suite["claim_boundary"],
        "files": collect_files(bundle_dir, manifest_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an outer SHA-256 manifest for one model's QA benchmark evidence."
    )
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--project-sha", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = build_qa_benchmark_manifest(
            bundle_dir=args.bundle_dir,
            suite_path=args.suite,
            provider=args.provider,
            model=args.model,
            project_sha=args.project_sha,
        )
    except (OSError, QABenchmarkError, QABenchmarkBundleError) as error:
        print(f"QA benchmark bundle error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
