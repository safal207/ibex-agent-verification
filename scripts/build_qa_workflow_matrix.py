#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from ibex_agent_verification.qa_benchmark import QABenchmarkError, load_qa_suite


class QAMatrixError(ValueError):
    """Raised when the QA suite workflow catalog is invalid."""


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise QAMatrixError(f"{label} must be a regular non-symlink file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise QAMatrixError(f"{path}: invalid {label} JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise QAMatrixError(f"{label} must be a JSON object")
    return payload


def _require_slug(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
        raise QAMatrixError(f"invalid {label}: {value!r}")
    return value


def _resolve_suite_path(*, repository_root: Path, relative_path: Any) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise QAMatrixError(f"suite path must be a non-empty string: {relative_path!r}")
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise QAMatrixError(f"suite path must stay inside the repository: {relative_path!r}")
    resolved = (repository_root / candidate).resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError as error:
        raise QAMatrixError(f"suite path escapes repository: {relative_path!r}") from error
    if resolved.is_symlink() or not resolved.is_file():
        raise QAMatrixError(f"suite path must reference a regular file: {relative_path!r}")
    return resolved


def build_workflow_matrix(catalog_path: Path) -> dict[str, list[dict[str, Any]]]:
    catalog_path = catalog_path.resolve()
    catalog = _load_object(catalog_path, label="QA suite catalog")
    if catalog.get("schema_version") != 1:
        raise QAMatrixError("QA suite catalog schema_version must equal 1")

    repository_root = catalog_path.parent.parent.resolve()
    models = catalog.get("models")
    suites = catalog.get("suites")
    if not isinstance(models, list) or not models:
        raise QAMatrixError("QA suite catalog models must be a non-empty array")
    if not isinstance(suites, list) or not suites:
        raise QAMatrixError("QA suite catalog suites must be a non-empty array")

    normalized_models: list[dict[str, str]] = []
    model_keys: set[tuple[str, str]] = set()
    model_slugs: set[str] = set()
    for index, raw_model in enumerate(models):
        if not isinstance(raw_model, dict):
            raise QAMatrixError(f"models[{index}] must be an object")
        provider = raw_model.get("provider")
        model = raw_model.get("model")
        slug = _require_slug(raw_model.get("slug"), label=f"models[{index}].slug")
        if not isinstance(provider, str) or not _PROVIDER_RE.fullmatch(provider):
            raise QAMatrixError(f"invalid models[{index}].provider: {provider!r}")
        if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
            raise QAMatrixError(f"invalid models[{index}].model: {model!r}")
        key = (provider, model)
        if key in model_keys:
            raise QAMatrixError(f"duplicate provider/model entry: {provider}/{model}")
        if slug in model_slugs:
            raise QAMatrixError(f"duplicate model slug: {slug}")
        model_keys.add(key)
        model_slugs.add(slug)
        normalized_models.append({"provider": provider, "model": model, "model_slug": slug})

    normalized_suites: list[dict[str, Any]] = []
    suite_ids: set[str] = set()
    suite_slugs: set[str] = set()
    suite_paths: set[str] = set()
    for index, raw_suite in enumerate(suites):
        if not isinstance(raw_suite, dict):
            raise QAMatrixError(f"suites[{index}] must be an object")
        declared_id = raw_suite.get("suite_id")
        slug = _require_slug(raw_suite.get("slug"), label=f"suites[{index}].slug")
        relative_path = raw_suite.get("path")
        expected_task_count = raw_suite.get("expected_task_count")
        if (
            isinstance(expected_task_count, bool)
            or not isinstance(expected_task_count, int)
            or not 1 <= expected_task_count <= 100
        ):
            raise QAMatrixError(
                f"suites[{index}].expected_task_count must be an integer from 1 through 100"
            )
        resolved = _resolve_suite_path(
            repository_root=repository_root,
            relative_path=relative_path,
        )
        try:
            suite = load_qa_suite(resolved)
        except QABenchmarkError as error:
            raise QAMatrixError(f"invalid suite {relative_path!r}: {error}") from error
        if declared_id != suite["suite_id"]:
            raise QAMatrixError(
                f"suite_id mismatch for {relative_path!r}: "
                f"catalog={declared_id!r} suite={suite['suite_id']!r}"
            )
        if len(suite["tasks"]) != expected_task_count:
            raise QAMatrixError(
                f"task count mismatch for {declared_id}: "
                f"catalog={expected_task_count} suite={len(suite['tasks'])}"
            )
        normalized_relative = resolved.relative_to(repository_root).as_posix()
        if declared_id in suite_ids:
            raise QAMatrixError(f"duplicate suite_id: {declared_id}")
        if slug in suite_slugs:
            raise QAMatrixError(f"duplicate suite slug: {slug}")
        if normalized_relative in suite_paths:
            raise QAMatrixError(f"duplicate suite path: {normalized_relative}")
        suite_ids.add(declared_id)
        suite_slugs.add(slug)
        suite_paths.add(normalized_relative)
        normalized_suites.append(
            {
                "suite_id": declared_id,
                "suite_slug": slug,
                "suite_path": normalized_relative,
                "task_count": expected_task_count,
            }
        )

    include: list[dict[str, Any]] = []
    for suite in normalized_suites:
        for model in normalized_models:
            include.append({**suite, **model})
    return {"include": include}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the QA catalog and emit a GitHub Actions matrix."
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        matrix = build_workflow_matrix(args.catalog)
        compact = json.dumps(matrix, separators=(",", ":"), sort_keys=True)
        if args.github_output is not None:
            output_path = args.github_output.resolve()
            with output_path.open("a", encoding="utf-8", newline="\n") as output:
                output.write(f"matrix={compact}\n")
    except (OSError, QAMatrixError) as error:
        print(f"QA workflow matrix error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(matrix, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
