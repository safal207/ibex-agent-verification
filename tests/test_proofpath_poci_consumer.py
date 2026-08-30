from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_proofpath_poci_consumer import (  # noqa: E402
    CELLS_DOMAIN,
    MULTIGRAPH_PROFILE,
    POLICY_PROFILE,
    REPORT_PROFILE,
    REQUIRED_GRAPHS,
    SOURCE_DOMAIN,
    digest,
    receipt_root,
    verify,
)


class ProofPathPoCIConsumerTests(unittest.TestCase):
    def make_case(self):
        source = {"profile_id": "demo.source", "items": [1, 2, 3]}
        source_digest = digest(SOURCE_DOMAIN, source)
        graph_roots = {
            name: "sha256:" + str(index + 1) * 64
            for index, name in enumerate(REQUIRED_GRAPHS)
        }
        cells = [
            {"cell_id": "proposal"},
            {"cell_id": "execution"},
            {"cell_id": "observation"},
        ]
        cells_root = digest(CELLS_DOMAIN, cells)
        multigraph_root = "sha256:" + "a" * 64
        consensus_root = "sha256:" + "b" * 64
        producer = {
            "repository": "safal207/ProofPath",
            "code_sha": "producer-head",
            "attestation_source_sha": "producer-merge",
            "attestation_signer_sha": "producer-merge",
            "workflow": (
                "safal207/ProofPath/.github/workflows/"
                "poci-signed-witness-network.yml"
            ),
            "report_sha256": "sha256:producer-report",
            "source_path": "source.valid.json",
        }
        expected = {
            "round_id": "round-1",
            "consensus_root": consensus_root,
            "source_digest": source_digest,
            "graph_set_id": "graph-set-1",
            "poci_envelope_id": "envelope-1",
            "graph_roots": graph_roots,
            "transition_cells_root": cells_root,
            "computed_multigraph_root": multigraph_root,
            "verified_attestation_count": 3,
        }
        policy = {
            "profile_id": POLICY_PROFILE,
            "producer": producer,
            "expected": expected,
            "consumer": {"consumer_id": "ibex-consumer"},
        }
        report = {
            "profile_id": REPORT_PROFILE,
            "round_id": expected["round_id"],
            "decision": "ACCEPT",
            "valid": True,
            "consensus_root": consensus_root,
            "consensus": {
                "source_digest": source_digest,
                "graph_set_id": expected["graph_set_id"],
                "poci_envelope_id": expected["poci_envelope_id"],
                "graph_roots": graph_roots,
                "transition_cells_root": cells_root,
                "computed_multigraph_root": multigraph_root,
            },
            "attestation_profile": "github-keyless-slsa-provenance",
            "verified_attestation_count": 3,
            "signer_workflow": producer["workflow"],
            "source_digest": producer["attestation_source_sha"],
            "signer_digest": producer["attestation_signer_sha"],
            "self_hosted_runners_denied": True,
        }
        recomputed = {
            "profile_id": MULTIGRAPH_PROFILE,
            "decision": "ACCEPT",
            "valid": True,
            "graph_set_id": expected["graph_set_id"],
            "poci_envelope_id": expected["poci_envelope_id"],
            "graphs": {
                name: {"root": root} for name, root in graph_roots.items()
            },
            "transition_cells": cells,
            "computed_multigraph_root": multigraph_root,
        }
        return policy, report, recomputed, source

    def run_case(self, policy, report, recomputed, source, **overrides):
        args = {
            "producer_report_digest": "sha256:producer-report",
            "producer_checkout_sha": "producer-head",
            "attestation_result_digest": "sha256:attestation-result",
            "consumer_repository": "safal207/ibex-agent-verification",
            "consumer_workflow": "consumer-workflow",
            "consumer_sha": "consumer-head",
        }
        args.update(overrides)
        return verify(policy, report, recomputed, source, **args)

    def test_valid_external_recomputation_accepts(self):
        case = self.make_case()
        result = self.run_case(*case)
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["accepted_consensus"]["graph_roots"]), 6)
        self.assertEqual(result["receipt_root"], receipt_root(result))

    def test_report_digest_substitution_challenges(self):
        case = self.make_case()
        result = self.run_case(*case, producer_report_digest="sha256:other")
        self.assertEqual(result["decision"], "CHALLENGE")
        self.assertIn("PRODUCER_REPORT_DIGEST_MISMATCH", result["reason_codes"])

    def test_missing_attestation_blocks(self):
        case = self.make_case()
        result = self.run_case(*case, attestation_result_digest=None)
        self.assertEqual(result["decision"], "BLOCK")
        self.assertIn("PRODUCER_ATTESTATION_UNVERIFIED", result["reason_codes"])

    def test_wrong_producer_commit_challenges(self):
        case = self.make_case()
        result = self.run_case(*case, producer_checkout_sha="other-head")
        self.assertEqual(result["decision"], "CHALLENGE")
        self.assertIn("PRODUCER_CODE_SHA_MISMATCH", result["reason_codes"])

    def test_source_byte_mutation_challenges(self):
        policy, report, recomputed, source = self.make_case()
        source["items"].append(4)
        result = self.run_case(policy, report, recomputed, source)
        self.assertEqual(result["decision"], "CHALLENGE")
        self.assertIn("PRODUCER_SOURCE_DIGEST_MISMATCH", result["reason_codes"])

    def test_graph_root_substitution_challenges(self):
        policy, report, recomputed, source = self.make_case()
        recomputed["graphs"]["authority"]["root"] = "sha256:" + "f" * 64
        result = self.run_case(policy, report, recomputed, source)
        self.assertEqual(result["decision"], "CHALLENGE")
        self.assertIn("EXTERNAL_GRAPH_ROOT_MISMATCH", result["reason_codes"])

    def test_transition_cell_mutation_challenges(self):
        policy, report, recomputed, source = self.make_case()
        recomputed["transition_cells"][1]["cell_id"] = "substituted"
        result = self.run_case(policy, report, recomputed, source)
        self.assertEqual(result["decision"], "CHALLENGE")
        self.assertIn("EXTERNAL_TRANSITION_CELLS_MISMATCH", result["reason_codes"])

    def test_multigraph_root_substitution_challenges(self):
        policy, report, recomputed, source = self.make_case()
        recomputed["computed_multigraph_root"] = "sha256:" + "e" * 64
        result = self.run_case(policy, report, recomputed, source)
        self.assertEqual(result["decision"], "CHALLENGE")
        self.assertIn("EXTERNAL_MULTIGRAPH_ROOT_MISMATCH", result["reason_codes"])

    def test_non_accepting_producer_report_blocks(self):
        policy, report, recomputed, source = self.make_case()
        report["decision"] = "HOLD"
        result = self.run_case(policy, report, recomputed, source)
        self.assertEqual(result["decision"], "BLOCK")
        self.assertIn("PRODUCER_REPORT_INVALID", result["reason_codes"])

    def test_receipt_root_is_deterministic(self):
        case = self.make_case()
        left = self.run_case(*copy.deepcopy(case))
        right = self.run_case(*copy.deepcopy(case))
        self.assertEqual(left["receipt_root"], right["receipt_root"])


if __name__ == "__main__":
    unittest.main()
