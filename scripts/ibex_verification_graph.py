#!/usr/bin/env python3
"""CLI for the deterministic Ibex CI verification graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ibex_agent_verification.verification_graph import (
    audit_workflow,
    build_plan,
    finalize_plan,
    load_policy,
    render_summary,
)


def _write_json(path: str | Path, value: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_summary(path: str | Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_summary(value), encoding="utf-8")


def _write_github_outputs(path: str | Path | None, plan: dict[str, Any]) -> None:
    if path is None:
        return
    depth = plan["decision"]["depth"]
    required = set(plan["decision"]["required_ci_nodes"])
    pairs = {
        "depth": depth,
        "changed_count": str(plan["source"]["changed_file_count"]),
        "require_schema": str("schema_vectors" in required).lower(),
        "require_authority": str("authority_invariants" in required).lower(),
        "require_wheel": str("installed_wheel" in required).lower(),
        "require_workflow_security": str("workflow_security" in required).lower(),
        "require_human": str(bool(plan["decision"]["required_external_nodes"])).lower(),
    }
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def command_validate(args: argparse.Namespace) -> int:
    load_policy(args.policy)
    return 0


def command_plan(args: argparse.Namespace) -> int:
    policy = load_policy(args.policy)
    changed_paths = json.loads(args.files_json)
    if not isinstance(changed_paths, list):
        raise ValueError("--files-json must decode to an array")
    plan = build_plan(changed_paths, args.head, policy)
    _write_json(args.output, plan)
    _write_summary(args.summary, plan)
    _write_github_outputs(args.github_output, plan)
    return 0


def command_finalize(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    results = json.loads(args.results_json)
    if not isinstance(results, dict):
        raise ValueError("--results-json must decode to an object")
    final = finalize_plan(plan, results)
    _write_json(args.output, final)
    _write_summary(args.summary, final)
    return 1 if final["verdict"]["status"] == "BLOCK" else 0


def command_audit_workflow(args: argparse.Namespace) -> int:
    report = audit_workflow(args.workflow)
    _write_json(args.output, report)
    return 1 if report["status"] == "BLOCK" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-policy")
    validate.add_argument("--policy", required=True)
    validate.set_defaults(func=command_validate)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--policy", required=True)
    plan.add_argument("--files-json", required=True)
    plan.add_argument("--head", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--summary")
    plan.add_argument("--github-output")
    plan.set_defaults(func=command_plan)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--plan", required=True)
    finalize.add_argument("--results-json", required=True)
    finalize.add_argument("--output", required=True)
    finalize.add_argument("--summary")
    finalize.set_defaults(func=command_finalize)

    audit = subparsers.add_parser("audit-workflow")
    audit.add_argument("--workflow", required=True)
    audit.add_argument("--output", required=True)
    audit.set_defaults(func=command_audit_workflow)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
