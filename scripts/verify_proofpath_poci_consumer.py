#!/usr/bin/env python3
"""Verify an attested ProofPath PoCI quorum through an Ibex consumer."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

POLICY_PROFILE = "ibex.poci.external-consumer-policy.v0.1"
RECEIPT_PROFILE = "ibex.poci.external-consumer-receipt.v0.1"
REPORT_PROFILE = "proofpath.poci.multigraph.witness-quorum.v0.1"
MULTIGRAPH_PROFILE = "proofpath.poci.multigraph.v0.1"
SOURCE_DOMAIN = b"proofpath:poci:multigraph:witness:v0.1:source\n"
CELLS_DOMAIN = b"proofpath:poci:multigraph:witness:v0.1:cells\n"
RECEIPT_DOMAIN = b"ibex:poci:external-consumer:v0.1:receipt\n"
ATTESTATION_DOMAIN = b"ibex:poci:external-consumer:v0.1:attestation-result\n"
REQUIRED_GRAPHS = (
    "causal",
    "intent",
    "authority",
    "state_transition",
    "evidence",
    "time_continuity",
)
RANK = {"ACCEPT": 0, "BLOCK": 1, "CHALLENGE": 2}
EXIT = {"ACCEPT": 0, "BLOCK": 3, "CHALLENGE": 4}


class DuplicateKeyError(ValueError):
    pass


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, json.JSONDecodeError, DuplicateKeyError) as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def load_object(path: Path) -> dict[str, Any]:
    value = load_value(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _has_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_has_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_float(item) for item in value)
    return False


def canonical(value: Any) -> bytes:
    if _has_float(value):
        raise ValueError("floating-point values are forbidden")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(domain: bytes, value: Any) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def receipt_root(receipt: dict[str, Any]) -> str:
    normalized = copy.deepcopy(receipt)
    normalized["receipt_root"] = None
    return digest(RECEIPT_DOMAIN, normalized)


def finding(code: str, decision: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "decision": decision, "path": path, "message": message}


def verify(
    policy: dict[str, Any],
    producer_report: dict[str, Any],
    recomputed: dict[str, Any],
    source: dict[str, Any],
    *,
    producer_report_digest: str,
    producer_checkout_sha: str,
    attestation_result_digest: str | None,
    consumer_repository: str,
    consumer_workflow: str,
    consumer_sha: str,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    producer = policy.get("producer") if isinstance(policy.get("producer"), dict) else {}
    expected = policy.get("expected") if isinstance(policy.get("expected"), dict) else {}
    consumer = policy.get("consumer") if isinstance(policy.get("consumer"), dict) else {}

    def add(code: str, decision: str, path: str, message: str) -> None:
        findings.append(finding(code, decision, path, message))

    if policy.get("profile_id") != POLICY_PROFILE:
        add("CONSUMER_POLICY_INVALID", "BLOCK", "$.profile_id", "unsupported policy")

    pinned_fields = (
        "repository",
        "code_sha",
        "attestation_source_sha",
        "attestation_signer_sha",
        "workflow",
        "report_sha256",
        "source_path",
    )
    if any(not isinstance(producer.get(key), str) or not producer.get(key) for key in pinned_fields):
        add("CONSUMER_POLICY_INVALID", "BLOCK", "$.producer", "producer pins are incomplete")

    expected_roots = expected.get("graph_roots")
    if not isinstance(expected_roots, dict) or set(expected_roots) != set(REQUIRED_GRAPHS):
        add(
            "CONSUMER_POLICY_INVALID",
            "BLOCK",
            "$.expected.graph_roots",
            "exactly six graph roots must be pinned",
        )
        expected_roots = {}

    if producer_report_digest != producer.get("report_sha256"):
        add(
            "PRODUCER_REPORT_DIGEST_MISMATCH",
            "CHALLENGE",
            "$.producer.report_sha256",
            "producer report subject bytes changed",
        )
    if attestation_result_digest is None:
        add(
            "PRODUCER_ATTESTATION_UNVERIFIED",
            "BLOCK",
            "$.producer.attestation",
            "keyless producer attestation is required",
        )
    if producer_checkout_sha != producer.get("code_sha"):
        add(
            "PRODUCER_CODE_SHA_MISMATCH",
            "CHALLENGE",
            "$.producer.code_sha",
            "recomputation used another ProofPath commit",
        )

    consensus = producer_report.get("consensus")
    if not isinstance(consensus, dict):
        consensus = {}
    producer_policy_ok = (
        producer_report.get("profile_id") == REPORT_PROFILE
        and producer_report.get("decision") == "ACCEPT"
        and producer_report.get("valid") is True
        and producer_report.get("attestation_profile")
        == "github-keyless-slsa-provenance"
        and producer_report.get("verified_attestation_count")
        == expected.get("verified_attestation_count")
        and producer_report.get("signer_workflow") == producer.get("workflow")
        and producer_report.get("source_digest")
        == producer.get("attestation_source_sha")
        and producer_report.get("signer_digest")
        == producer.get("attestation_signer_sha")
        and producer_report.get("self_hosted_runners_denied") is True
    )
    if not producer_policy_ok:
        add(
            "PRODUCER_REPORT_INVALID",
            "BLOCK",
            "$.producer_report",
            "producer report violates pinned provenance policy",
        )

    producer_values = {
        "round_id": producer_report.get("round_id"),
        "consensus_root": producer_report.get("consensus_root"),
        "source_digest": consensus.get("source_digest"),
        "graph_set_id": consensus.get("graph_set_id"),
        "poci_envelope_id": consensus.get("poci_envelope_id"),
        "graph_roots": consensus.get("graph_roots"),
        "transition_cells_root": consensus.get("transition_cells_root"),
        "computed_multigraph_root": consensus.get("computed_multigraph_root"),
    }
    for key, actual in producer_values.items():
        if actual != expected.get(key):
            add(
                "PRODUCER_CONSENSUS_MISMATCH",
                "CHALLENGE",
                f"$.expected.{key}",
                f"producer consensus mismatch: {key}",
            )

    source_digest = digest(SOURCE_DOMAIN, source)
    if source_digest != expected.get("source_digest"):
        add(
            "PRODUCER_SOURCE_DIGEST_MISMATCH",
            "CHALLENGE",
            "$.producer.source_path",
            "checked-out source bytes differ",
        )

    graphs = recomputed.get("graphs")
    if not isinstance(graphs, dict):
        graphs = {}
    roots = {
        name: graphs.get(name, {}).get("root")
        if isinstance(graphs.get(name), dict)
        else None
        for name in REQUIRED_GRAPHS
    }
    cells = recomputed.get("transition_cells")
    cells = cells if isinstance(cells, list) else []
    cells_root = digest(CELLS_DOMAIN, cells)

    if not (
        recomputed.get("profile_id") == MULTIGRAPH_PROFILE
        and recomputed.get("decision") == "ACCEPT"
        and recomputed.get("valid") is True
        and len(graphs) == 6
        and len(cells) == 3
    ):
        add(
            "EXTERNAL_RECOMPUTATION_FAILED",
            "BLOCK",
            "$.recomputed_report",
            "external build did not accept six graphs and three cells",
        )
    if roots != expected_roots:
        add(
            "EXTERNAL_GRAPH_ROOT_MISMATCH",
            "CHALLENGE",
            "$.recomputed_report.graphs",
            "external graph-root vector differs",
        )
    if cells_root != expected.get("transition_cells_root"):
        add(
            "EXTERNAL_TRANSITION_CELLS_MISMATCH",
            "CHALLENGE",
            "$.recomputed_report.transition_cells",
            "external transition-cell root differs",
        )
    if recomputed.get("computed_multigraph_root") != expected.get(
        "computed_multigraph_root"
    ):
        add(
            "EXTERNAL_MULTIGRAPH_ROOT_MISMATCH",
            "CHALLENGE",
            "$.recomputed_report.computed_multigraph_root",
            "external multi-graph root differs",
        )

    unique = {
        (item["code"], item["path"], item["message"]): item for item in findings
    }
    findings = sorted(
        unique.values(),
        key=lambda item: (-RANK[item["decision"]], item["code"], item["path"]),
    )
    primary = findings[0] if findings else None
    decision = primary["decision"] if primary else "ACCEPT"

    receipt: dict[str, Any] = {
        "profile_id": RECEIPT_PROFILE,
        "decision": decision,
        "primary_reason_code": primary["code"] if primary else None,
        "reason_codes": sorted({item["code"] for item in findings}),
        "findings": findings,
        "consumer": {
            "consumer_id": consumer.get("consumer_id"),
            "repository": consumer_repository,
            "workflow": consumer_workflow,
            "commit_sha": consumer_sha,
        },
        "producer": {
            "repository": producer.get("repository"),
            "code_sha": producer_checkout_sha,
            "attestation_source_sha": producer.get("attestation_source_sha"),
            "attestation_signer_sha": producer.get("attestation_signer_sha"),
            "workflow": producer.get("workflow"),
            "report_sha256": producer_report_digest,
            "attestation_result_sha256": attestation_result_digest,
        },
        "accepted_consensus": {
            "round_id": expected.get("round_id"),
            "consensus_root": expected.get("consensus_root"),
            "source_digest": source_digest,
            "graph_set_id": recomputed.get("graph_set_id"),
            "poci_envelope_id": recomputed.get("poci_envelope_id"),
            "graph_roots": roots,
            "transition_cells_root": cells_root,
            "computed_multigraph_root": recomputed.get("computed_multigraph_root"),
        },
        "verification": {
            "producer_attestation_verified": attestation_result_digest is not None,
            "producer_report_digest_verified": (
                producer_report_digest == producer.get("report_sha256")
            ),
            "producer_code_sha_verified": producer_checkout_sha == producer.get("code_sha"),
            "source_recomputed": True,
            "six_graph_roots_recomputed": True,
            "transition_cells_recomputed": True,
            "consumer_attestation_required": True,
        },
        "honest_limitations": [
            "ProofPath and Ibex use different repositories and workflow identities",
            "both repositories are currently controlled by the same GitHub account owner",
            "this proves evidence consistency, not objective real-world truth",
        ],
        "receipt_root": None,
        "valid": decision == "ACCEPT",
    }
    receipt["receipt_root"] = receipt_root(receipt)
    return receipt


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--producer-report", type=Path, required=True)
    parser.add_argument("--recomputed-report", type=Path, required=True)
    parser.add_argument("--producer-source", type=Path, required=True)
    parser.add_argument("--producer-checkout-sha", required=True)
    parser.add_argument("--attestation-result", type=Path, required=True)
    parser.add_argument("--consumer-repository", required=True)
    parser.add_argument("--consumer-workflow", required=True)
    parser.add_argument("--consumer-sha", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        policy = load_object(args.policy)
        producer_report = load_object(args.producer_report)
        recomputed = load_object(args.recomputed_report)
        source = load_object(args.producer_source)
        attestation_result = load_value(args.attestation_result)
        receipt = verify(
            policy,
            producer_report,
            recomputed,
            source,
            producer_report_digest=file_digest(args.producer_report),
            producer_checkout_sha=args.producer_checkout_sha,
            attestation_result_digest=digest(ATTESTATION_DOMAIN, attestation_result),
            consumer_repository=args.consumer_repository,
            consumer_workflow=args.consumer_workflow,
            consumer_sha=args.consumer_sha,
        )
        code = EXIT[receipt["decision"]]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        receipt = {
            "profile_id": RECEIPT_PROFILE,
            "decision": "BLOCK",
            "primary_reason_code": "EXTERNAL_CONSUMER_INTERNAL_FAIL_CLOSED",
            "reason_codes": ["EXTERNAL_CONSUMER_INTERNAL_FAIL_CLOSED"],
            "findings": [
                finding(
                    "EXTERNAL_CONSUMER_INTERNAL_FAIL_CLOSED",
                    "BLOCK",
                    "$",
                    str(exc),
                )
            ],
            "valid": False,
            "receipt_root": None,
        }
        receipt["receipt_root"] = receipt_root(receipt)
        code = 1

    text = (
        json.dumps(receipt, indent=2, ensure_ascii=False)
        if args.pretty
        else json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    ) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
