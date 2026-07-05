"""Constants for temporal relation verification."""

import re

TEMPORAL_RELATION_CONTEXT = (
    "urn:ibex-agent-verification:temporal-phase-relation:v1"
)
TRANSITION_OBSERVATION_CONTEXT = (
    "urn:ibex-agent-verification:transition-observation:v1"
)
COMPARISON_CONTEXT = (
    "urn:ibex-agent-verification:expected-observed-transition-comparison:v1"
)

MATCH = "MATCH"
MISSING_OBSERVATION = "MISSING_OBSERVATION"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
PHASE_MISMATCH = "PHASE_MISMATCH"
TEMPORAL_MISMATCH = "TEMPORAL_MISMATCH"
STALE_EVIDENCE = "STALE_EVIDENCE"
OUTCOME_DEVIATION = "OUTCOME_DEVIATION"
NON_RECOMPUTABLE = "NON_RECOMPUTABLE"

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
RELATION_KEYS = {
    "@context", "source", "target", "relation_type", "transition_id",
    "expected_phase", "valid_from", "valid_until",
    "evidence_max_age_seconds", "expected_outcome", "evidence_refs",
}
OBSERVATION_KEYS = {
    "@context", "source", "target", "relation_type", "transition_id",
    "observed_phase", "observed_at", "observed_outcome", "evidence_refs",
}
ARTIFACT_KEYS = {"artifact_id", "artifact_type", "digest"}
EVIDENCE_KEYS = {"ref", "digest", "captured_at"}
