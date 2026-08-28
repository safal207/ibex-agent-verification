"""Conformance tests for the grant-consumption execution-safety boundary."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from ibex_agent_verification.execution_safety import (
    ConsumptionBinding,
    ExecutionGuarantee,
    ExecutionSafetyVerdict,
    verify_execution_safety,
)


ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT / "conformance" / "execution-consumption-v1.json"
EXPECTED_CASE_NAMES = {
    "advisory-ledger-check-then-separate-dispatch",
    "local-atomic-single-instance",
    "local-atomic-multi-worker",
    "shared-ledger-consume-then-separate-http-dispatch",
    "outbox-consume-and-enqueue-same-transaction",
    "outbox-with-occurrence-bound-endpoint-idempotency",
    "tool-idempotency-without-use-token",
    "tool-idempotency-unbound-use-token",
    "tool-idempotency-occurrence-bound-use-token",
}


class ExecutionSafetyTests(unittest.TestCase):
    def test_published_conformance_vectors(self):
        profile = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
        self.assertEqual(profile["profile"], "execution-consumption-v1")
        self.assertEqual(profile["invariant"], "Authority follows atomicity")
        self.assertEqual(
            {case["name"] for case in profile["cases"]},
            EXPECTED_CASE_NAMES,
        )
        self.assertEqual(len(profile["cases"]), len(EXPECTED_CASE_NAMES))

        for case in profile["cases"]:
            with self.subTest(case=case["name"]):
                binding = ConsumptionBinding.from_mapping(case["binding"])
                result = verify_execution_safety(binding)
                self.assertEqual(result.verdict.value, case["expected"]["verdict"])
                self.assertEqual(result.guarantee.value, case["expected"]["guarantee"])
                self.assertEqual(result.reason_code, case["expected"]["reason_code"])

    def test_local_atomic_multi_worker_cannot_claim_cross_instance_safety(self):
        binding = ConsumptionBinding.from_mapping(
            {
                "execution_binding": "internal",
                "consumption_authority": "worker-local-state",
                "consumption_mode": "local_atomic",
                "executor_scope": "multi_instance",
                "dispatch_commitment_bound": True,
                "use_token": None,
                "use_token_bound": False,
                "endpoint_idempotency_enforced": False,
            }
        )

        result = verify_execution_safety(binding)

        self.assertEqual(
            result.verdict,
            ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
        )
        self.assertEqual(result.guarantee, ExecutionGuarantee.SINGLE_INSTANCE)
        self.assertEqual(
            result.reason_code,
            "LOCAL_STATE_NO_CROSS_INSTANCE_PROTECTION",
        )

    def test_atomic_ledger_with_separate_dispatch_fails_closed(self):
        binding = ConsumptionBinding.from_mapping(
            {
                "execution_binding": "external",
                "consumption_authority": "shared-ledger",
                "consumption_mode": "shared_atomic",
                "executor_scope": "multi_instance",
                "dispatch_commitment_bound": False,
                "use_token": None,
                "use_token_bound": False,
                "endpoint_idempotency_enforced": False,
            }
        )

        result = verify_execution_safety(binding)

        self.assertEqual(result.verdict, ExecutionSafetyVerdict.NOT_EXECUTION_SAFE)
        self.assertEqual(result.guarantee, ExecutionGuarantee.NONE)
        self.assertEqual(result.reason_code, "DISPATCH_OUTSIDE_ATOMIC_BOUNDARY")

    def test_atomic_outbox_does_not_claim_exclusive_external_execution(self):
        binding = ConsumptionBinding.from_mapping(
            {
                "execution_binding": "external",
                "consumption_authority": "dispatch-ledger",
                "consumption_mode": "outbox_atomic",
                "executor_scope": "multi_instance",
                "dispatch_commitment_bound": True,
                "use_token": None,
                "use_token_bound": False,
                "endpoint_idempotency_enforced": False,
            }
        )

        result = verify_execution_safety(binding)

        self.assertEqual(
            result.verdict,
            ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
        )
        self.assertEqual(result.guarantee, ExecutionGuarantee.ATOMIC_ENQUEUE)
        self.assertEqual(
            result.reason_code,
            "OUTBOX_DELIVERY_REPLAY_PROTECTION_UNPROVEN",
        )

    def test_tool_endpoint_needs_bound_use_token_and_enforcement(self):
        unbound_token = ConsumptionBinding.from_mapping(
            {
                "execution_binding": "external",
                "consumption_authority": "tool-endpoint",
                "consumption_mode": "tool_idempotent",
                "executor_scope": "multi_instance",
                "dispatch_commitment_bound": False,
                "use_token": "caller-generated-retry-token",
                "use_token_bound": False,
                "endpoint_idempotency_enforced": True,
            }
        )
        result = verify_execution_safety(unbound_token)
        self.assertEqual(
            result.verdict,
            ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
        )
        self.assertEqual(result.reason_code, "USE_TOKEN_BINDING_UNPROVEN")

        missing_enforcement = ConsumptionBinding.from_mapping(
            {
                "execution_binding": "external",
                "consumption_authority": "tool-endpoint",
                "consumption_mode": "tool_idempotent",
                "executor_scope": "multi_instance",
                "dispatch_commitment_bound": False,
                "use_token": "grant-42:occurrence-7",
                "use_token_bound": True,
                "endpoint_idempotency_enforced": False,
            }
        )
        result = verify_execution_safety(missing_enforcement)
        self.assertEqual(
            result.verdict,
            ExecutionSafetyVerdict.REPLAY_PROTECTION_UNPROVEN,
        )
        self.assertEqual(result.reason_code, "ENDPOINT_IDEMPOTENCY_UNPROVEN")

    def test_binding_is_closed_and_immutable(self):
        value = {
            "execution_binding": "external",
            "consumption_authority": "dispatch-ledger",
            "consumption_mode": "outbox_atomic",
            "executor_scope": "multi_instance",
            "dispatch_commitment_bound": True,
            "use_token": None,
            "use_token_bound": False,
            "endpoint_idempotency_enforced": False,
        }
        binding = ConsumptionBinding.from_mapping(value)

        with self.assertRaises(FrozenInstanceError):
            binding.consumption_authority = "mutated"  # type: ignore[misc]

        with self.assertRaisesRegex(ValueError, "unknown fields"):
            ConsumptionBinding.from_mapping({**value, "unbound_hint": "unsafe"})

    def test_invalid_or_empty_use_token_is_rejected(self):
        base = {
            "execution_binding": "external",
            "consumption_authority": "tool-endpoint",
            "consumption_mode": "tool_idempotent",
            "executor_scope": "multi_instance",
            "dispatch_commitment_bound": False,
            "use_token_bound": True,
            "endpoint_idempotency_enforced": True,
        }

        with self.assertRaisesRegex(ValueError, "use_token"):
            ConsumptionBinding.from_mapping({**base, "use_token": ""})


if __name__ == "__main__":
    unittest.main()
