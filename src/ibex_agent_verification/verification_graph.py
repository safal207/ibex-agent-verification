"""Deterministic CI verification graph for Ibex pull requests."""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ACTION_PIN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def load_policy(path: str | Path) -> dict[str, Any]:
    """Load and validate the machine-readable verification graph policy."""

    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "contract",
        "version",
        "authority",
        "defaultDepth",
        "depthOrder",
        "pathRules",
        "nodes",
        "edges",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise ValueError(f"verification graph policy missing fields: {missing}")
    depth_order = policy["depthOrder"]
    if depth_order != ["L1", "L2", "L3", "L4"]:
        raise ValueError("depthOrder must be exactly L1, L2, L3, L4")
    if policy["defaultDepth"] not in depth_order:
        raise ValueError("defaultDepth is not declared in depthOrder")
    if policy["authority"] != "verification-plan-only":
        raise ValueError("verification graph must not grant merge authority")

    node_ids: set[str] = set()
    for node in policy["nodes"]:
        if not isinstance(node, dict):
            raise ValueError("every graph node must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("every graph node requires a non-empty id")
        if node_id in node_ids:
            raise ValueError(f"duplicate graph node id: {node_id}")
        node_ids.add(node_id)
        if node.get("minimumDepth") not in depth_order:
            raise ValueError(f"node {node_id} has invalid minimumDepth")
        if node.get("execution") not in {"ci", "external"}:
            raise ValueError(f"node {node_id} has invalid execution class")

    allowed_edge_nodes = node_ids | {"changed_paths", "depth_decision", "final_verdict"}
    for edge in policy["edges"]:
        if (
            not isinstance(edge, list)
            or len(edge) != 2
            or any(not isinstance(item, str) for item in edge)
        ):
            raise ValueError("every graph edge must be a two-string array")
        unknown = [item for item in edge if item not in allowed_edge_nodes]
        if unknown:
            raise ValueError(f"graph edge references unknown nodes: {unknown}")

    return policy


def classify_changed_paths(
    changed_paths: Sequence[str],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify authoritative changed paths into a fail-closed L1-L4 depth."""

    if not isinstance(changed_paths, Sequence) or isinstance(changed_paths, (str, bytes)):
        raise TypeError("changed_paths must be a sequence of repository-relative paths")
    normalized: list[str] = []
    for raw_path in changed_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("changed paths must be non-empty strings")
        path = raw_path.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if path.startswith("../") or path.startswith("/"):
            raise ValueError(f"changed path escapes repository: {raw_path}")
        normalized.append(path)

    normalized = sorted(set(normalized))
    if not normalized:
        raise ValueError("at least one changed path is required")

    depth_order = list(policy["depthOrder"])
    depth_index = {depth: index for index, depth in enumerate(depth_order)}
    default_depth = str(policy["defaultDepth"])
    selected_depth = "L1"
    classifications: list[dict[str, str]] = []
    unknown_paths: list[str] = []

    for path in normalized:
        matches: list[tuple[int, str, str]] = []
        for rule in policy["pathRules"]:
            rule_depth = rule["depth"]
            for pattern in rule["patterns"]:
                if fnmatch.fnmatchcase(path, pattern):
                    matches.append((depth_index[rule_depth], rule_depth, rule["reason"]))
                    break
        if matches:
            _, path_depth, reason = max(matches, key=lambda item: item[0])
        else:
            path_depth = default_depth
            reason = "unknown path fails closed to the default depth"
            unknown_paths.append(path)
        if depth_index[path_depth] > depth_index[selected_depth]:
            selected_depth = path_depth
        classifications.append({"path": path, "depth": path_depth, "reason": reason})

    return {
        "depth": selected_depth,
        "changed_paths": normalized,
        "classifications": classifications,
        "unknown_paths": unknown_paths,
    }


def build_plan(
    changed_paths: Sequence[str],
    head_sha: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic verification plan for one exact pull-request head."""

    if not isinstance(head_sha, str) or _SHA40.fullmatch(head_sha) is None:
        raise ValueError("head_sha must be 40 lowercase hexadecimal characters")
    classification = classify_changed_paths(changed_paths, policy)
    depth_order = list(policy["depthOrder"])
    selected_index = depth_order.index(classification["depth"])

    nodes: list[dict[str, Any]] = []
    required_ci_nodes: list[str] = []
    required_external_nodes: list[str] = []
    for source_node in policy["nodes"]:
        node = dict(source_node)
        required = depth_order.index(node["minimumDepth"]) <= selected_index
        node["required"] = required
        node["status"] = "PLANNED" if required else "NOT_REQUIRED"
        nodes.append(node)
        if required and node["execution"] == "ci":
            required_ci_nodes.append(node["id"])
        elif required:
            required_external_nodes.append(node["id"])

    return {
        "schema_version": 1,
        "contract": policy["contract"],
        "policy_version": policy["version"],
        "authority": policy["authority"],
        "merge_authorized": False,
        "source": {
            "head_sha": head_sha,
            "changed_file_count": len(classification["changed_paths"]),
            "changed_paths": classification["changed_paths"],
        },
        "decision": {
            "depth": classification["depth"],
            "unknown_paths": classification["unknown_paths"],
            "classifications": classification["classifications"],
            "required_ci_nodes": required_ci_nodes,
            "required_external_nodes": required_external_nodes,
            "permitted_next_transition": "RUN_REQUIRED_VERIFICATION",
        },
        "graph": {
            "nodes": nodes,
            "edges": [list(edge) for edge in policy["edges"]],
        },
    }


def finalize_plan(
    plan: Mapping[str, Any],
    results: Mapping[str, str],
) -> dict[str, Any]:
    """Bind CI results to the plan and derive a fail-closed graph verdict."""

    if plan.get("authority") != "verification-plan-only":
        raise ValueError("plan authority boundary is invalid")
    normalized_results = {
        str(node_id): str(status).upper() for node_id, status in results.items()
    }
    allowed_statuses = {"SUCCESS", "FAILURE", "CANCELLED", "SKIPPED"}
    invalid_statuses = sorted(
        status for status in normalized_results.values() if status not in allowed_statuses
    )
    if invalid_statuses:
        raise ValueError(f"unsupported result statuses: {invalid_statuses}")

    updated_nodes: list[dict[str, Any]] = []
    blocking_nodes: list[str] = []
    external_nodes: list[str] = []

    for source_node in plan["graph"]["nodes"]:
        node = dict(source_node)
        if not node["required"]:
            node["status"] = "NOT_REQUIRED"
        elif node["execution"] == "external":
            node["status"] = "REQUIRED_EXTERNAL"
            external_nodes.append(node["id"])
        else:
            node["status"] = normalized_results.get(node["id"], "MISSING")
            if node["status"] != "SUCCESS":
                blocking_nodes.append(node["id"])
        updated_nodes.append(node)

    if blocking_nodes:
        verdict = "BLOCK"
        next_transition = "REPAIR_AND_RERUN"
    elif external_nodes:
        verdict = "PASS_WITH_EXTERNAL_GATE"
        next_transition = "REQUEST_BINDING_HUMAN_REVIEW"
    else:
        verdict = "PASS"
        next_transition = "EVALUATE_REPOSITORY_MERGE_POLICY"

    final = json.loads(json.dumps(plan))
    final["graph"]["nodes"] = updated_nodes
    final["verdict"] = {
        "status": verdict,
        "blocking_nodes": blocking_nodes,
        "external_nodes": external_nodes,
        "permitted_next_transition": next_transition,
    }
    final["merge_authorized"] = False
    return final


def audit_workflow(path: str | Path) -> dict[str, Any]:
    """Audit the verification workflow's exact-head and permission boundaries."""

    workflow_path = Path(path)
    text = workflow_path.read_text(encoding="utf-8")
    findings: list[str] = []

    required_snippets = {
        "pull_request trigger": "pull_request:",
        "read-only top-level permissions": "permissions: {}",
        "fork-aware repository checkout": (
            "repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}"
        ),
        "exact head checkout": "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
        "credential persistence disabled": "persist-credentials: false",
        "PR-scoped concurrency": "group: ibex-verification-graph-${{ github.event.pull_request.number || github.ref }}",
        "explicit non-authority result": "merge_authorized",
    }
    for label, snippet in required_snippets.items():
        if snippet not in text:
            findings.append(f"missing {label}")

    forbidden_snippets = {
        "pull_request_target is forbidden": "pull_request_target:",
        "write-all is forbidden": "permissions: write-all",
        "persisted checkout credentials are forbidden": "persist-credentials: true",
    }
    for label, snippet in forbidden_snippets.items():
        if snippet in text:
            findings.append(label)

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if not stripped.startswith("uses:"):
            continue
        action_ref = stripped.removeprefix("uses:").strip()
        if action_ref.startswith("./"):
            continue
        if _ACTION_PIN.fullmatch(action_ref) is None:
            findings.append(f"action is not pinned to a 40-character commit: {action_ref}")

    return {
        "workflow": workflow_path.as_posix(),
        "status": "PASS" if not findings else "BLOCK",
        "findings": findings,
    }


def render_summary(record: Mapping[str, Any]) -> str:
    """Render a stable human-facing GitHub Job Summary."""

    depth = record["decision"]["depth"]
    verdict = record.get("verdict", {}).get("status", "PLANNED")
    head = record["source"]["head_sha"]
    lines = [
        "# Ibex Verification Graph",
        "",
        f"**Exact head:** `{head}`  ",
        f"**Selected depth:** `{depth}`  ",
        f"**Graph verdict:** `{verdict}`  ",
        f"**Merge authorized:** `{str(record.get('merge_authorized', False)).lower()}`",
        "",
        "```mermaid",
        "flowchart LR",
        '  A["Authoritative changed paths"] --> B["L1-L4 depth decision"]',
        '  B --> C["Exact-head binding"]',
        '  B --> D["Graph contract"]',
        '  B --> E["Python contract suite"]',
        '  C --> F["Schema + vectors"]',
        '  D --> F',
        '  E --> G["Authority invariants"]',
        '  F --> H["Installed-wheel boundary"]',
        '  G --> H',
        '  H --> I["Workflow security"]',
        '  H --> J["Binding human gate"]',
        '  I --> K["PASS / BLOCK / EXTERNAL GATE"]',
        '  J --> K',
        "```",
        "",
        "## Required nodes",
        "",
        "| Node | Execution | Required | Status |",
        "|---|---|---:|---|",
    ]
    for node in record["graph"]["nodes"]:
        lines.append(
            f"| `{node['id']}` | {node['execution']} | "
            f"{'yes' if node['required'] else 'no'} | `{node['status']}` |"
        )

    lines.extend(
        [
            "",
            "## Changed-path evidence",
            "",
            "| Path | Depth | Reason |",
            "|---|---:|---|",
        ]
    )
    for item in record["decision"]["classifications"]:
        path = _escape_markdown_cell(item["path"])
        reason = _escape_markdown_cell(item["reason"])
        lines.append(f"| `{path}` | `{item['depth']}` | {reason} |")

    lines.extend(
        [
            "",
            "> This graph is evidence and routing input only. It never authorizes merge.",
            "",
        ]
    )
    return "\n".join(lines)


def _escape_markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")
