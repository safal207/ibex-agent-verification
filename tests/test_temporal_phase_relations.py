from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from ibex_agent_verification.temporal_phase_relations import (
    IDENTITY_MISMATCH,
    MATCH,
    MISSING_OBSERVATION,
    NON_RECOMPUTABLE,
    OUTCOME_DEVIATION,
    PHASE_MISMATCH,
    STALE_EVIDENCE,
    TEMPORAL_MISMATCH,
    compare_expected_to_observed,
    temporal_phase_relation_id,
    transition_observation_id,
)

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / "qa/temporal-phase-relation-vector.json"


def _vector() -> dict:
    return json.loads(VECTOR.read_text(encoding="utf-8"))


class TemporalPhaseRelationTests(unittest.TestCase):
    def test_published_vector_matches_and_remains_non_authorizing(self) -> None:
        vector = _vector()
        result = compare_expected_to_observed(vector["expected"], vector["observed"])
        self.assertEqual(result["status"], MATCH)
        self.assertTrue(result["transition_supported"])
        self.assertFalse(result["transition_authorized"])
        self.assertEqual(result["comparison_id"], vector["comparison_id"])
        self.assertEqual(
            temporal_phase_relation_id(vector["expected"]),
            vector["expected_relation_id"],
        )
        self.assertEqual(
            transition_observation_id(vector["observed"]),
            vector["observed_relation_id"],
        )

    def test_missing_observation_blocks(self) -> None:
        result = compare_expected_to_observed(_vector()["expected"], None)
        self.assertEqual(result["status"], MISSING_OBSERVATION)
        self.assertTrue(result["blocking"])

    def test_changed_head_digest_is_identity_mismatch(self) -> None:
        vector = _vector()
        observed = copy.deepcopy(vector["observed"])
        observed["source"]["digest"] = "sha256:" + "9" * 64
        result = compare_expected_to_observed(vector["expected"], observed)
        self.assertEqual(result["status"], IDENTITY_MISMATCH)

    def test_wrong_lifecycle_phase_blocks(self) -> None:
        vector = _vector()
        observed = copy.deepcopy(vector["observed"])
        observed["observed_phase"] = "POST_MERGE"
        result = compare_expected_to_observed(vector["expected"], observed)
        self.assertEqual(result["status"], PHASE_MISMATCH)

    def test_valid_until_is_exclusive(self) -> None:
        vector = _vector()
        observed = copy.deepcopy(vector["observed"])
        observed["observed_at"] = vector["expected"]["valid_until"]
        observed["evidence_refs"][0]["captured_at"] = observed["observed_at"]
        result = compare_expected_to_observed(vector["expected"], observed)
        self.assertEqual(result["status"], TEMPORAL_MISMATCH)

    def test_stale_evidence_blocks_even_inside_relation_window(self) -> None:
        vector = _vector()
        observed = copy.deepcopy(vector["observed"])
        observed["evidence_refs"][0]["captured_at"] = "2026-07-05T09:00:00Z"
        result = compare_expected_to_observed(vector["expected"], observed)
        self.assertEqual(result["status"], STALE_EVIDENCE)

    def test_future_evidence_is_stale(self) -> None:
        vector = _vector()
        observed = copy.deepcopy(vector["observed"])
        observed["evidence_refs"][0]["captured_at"] = "2026-07-05T10:31:00Z"
        result = compare_expected_to_observed(vector["expected"], observed)
        self.assertEqual(result["status"], STALE_EVIDENCE)

    def test_outcome_difference_is_reported_after_identity_time_and_phase_match(self) -> None:
        vector = _vector()
        observed = copy.deepcopy(vector["observed"])
        observed["observed_outcome"]["status"] = "FAILURE"
        result = compare_expected_to_observed(vector["expected"], observed)
        self.assertEqual(result["status"], OUTCOME_DEVIATION)

    def test_noncanonical_float_fails_closed(self) -> None:
        vector = _vector()
        expected = copy.deepcopy(vector["expected"])
        expected["expected_outcome"]["score"] = 0.9
        result = compare_expected_to_observed(expected, vector["observed"])
        self.assertEqual(result["status"], NON_RECOMPUTABLE)

    def test_evidence_order_does_not_change_identifiers(self) -> None:
        vector = _vector()
        expected = copy.deepcopy(vector["expected"])
        expected["evidence_refs"].append(
            {
                "ref": "artifact://policy/v1",
                "digest": "sha256:" + "d" * 64,
                "captured_at": "2026-07-05T10:20:00Z",
            }
        )
        reversed_expected = copy.deepcopy(expected)
        reversed_expected["evidence_refs"].reverse()
        self.assertEqual(
            temporal_phase_relation_id(expected),
            temporal_phase_relation_id(reversed_expected),
        )

    def test_duplicate_evidence_fails_closed(self) -> None:
        vector = _vector()
        observed = copy.deepcopy(vector["observed"])
        observed["evidence_refs"].append(copy.deepcopy(observed["evidence_refs"][0]))
        result = compare_expected_to_observed(vector["expected"], observed)
        self.assertEqual(result["status"], NON_RECOMPUTABLE)


class TemporalPhaseSchemaParityTests(unittest.TestCase):
    def test_packaged_schema_matches_repository_schema(self) -> None:
        repository_schema = ROOT / "schemas/expected_observed_transition_comparison_v1.schema.json"
        packaged_schema = (
            ROOT
            / "src/ibex_agent_verification/schemas/expected_observed_transition_comparison_v1.schema.json"
        )
        self.assertEqual(
            json.loads(repository_schema.read_text(encoding="utf-8")),
            json.loads(packaged_schema.read_text(encoding="utf-8")),
        )


if __name__ == "__main__":
    unittest.main()
