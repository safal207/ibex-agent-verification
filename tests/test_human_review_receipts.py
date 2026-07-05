from __future__ import annotations

import copy
import unittest

from ibex_agent_verification.human_review_receipts import (
    evaluate_human_review_gate,
    human_review_receipt_id,
)

HEAD = "a" * 40
NOW = "2026-07-05T18:00:00Z"
BASE_REVIEW = {
    "review_id": 101,
    "reviewer": "maintainer",
    "state": "APPROVED",
    "commit_id": HEAD,
    "submitted_at": "2026-07-05T17:59:00Z",
    "review_url": "https://github.com/o/r/pull/1#pullrequestreview-101",
    "reviewer_permission": "write",
}


def _gate(
    reviews: list[dict],
    *,
    author: str = "author",
    head: str = HEAD,
) -> dict:
    return evaluate_human_review_gate(
        repository="o/r",
        pull_request_number=1,
        current_head=head,
        author=author,
        reviews=reviews,
        observed_at=NOW,
        policy_version="review-policy-v1",
    )


class HumanReviewReceiptTests(unittest.TestCase):
    def test_current_eligible_approval_satisfies_gate_without_merge_authority(self) -> None:
        gate = _gate([BASE_REVIEW])
        self.assertEqual(gate["status"], "SATISFIED")
        self.assertTrue(gate["gate_satisfied"])
        self.assertFalse(gate["merge_authorized"])
        self.assertEqual(
            gate["relation_bundle"]["comparison"]["status"],
            "MATCH",
        )
        self.assertFalse(
            gate["relation_bundle"]["comparison"]["transition_authorized"]
        )
        self.assertEqual(
            human_review_receipt_id(gate["receipt"]),
            gate["receipt"]["receipt_id"],
        )

    def test_no_decisive_review_requires_external_gate(self) -> None:
        commented = copy.deepcopy(BASE_REVIEW)
        commented["state"] = "COMMENTED"
        gate = _gate([commented])
        self.assertEqual(gate["status"], "REQUIRED_EXTERNAL")
        self.assertEqual(gate["reasons"][0]["code"], "NO_DECISIVE_REVIEWS")

    def test_approval_on_old_head_is_stale(self) -> None:
        review = copy.deepcopy(BASE_REVIEW)
        review["commit_id"] = "b" * 40
        gate = _gate([review])
        self.assertEqual(gate["status"], "REQUIRED_EXTERNAL")
        self.assertEqual(gate["reasons"][0]["code"], "STALE_HEAD")

    def test_latest_change_request_invalidates_prior_approval(self) -> None:
        change_request = copy.deepcopy(BASE_REVIEW)
        change_request["review_id"] = 102
        change_request["state"] = "CHANGES_REQUESTED"
        change_request["submitted_at"] = "2026-07-05T17:59:30Z"
        gate = _gate([BASE_REVIEW, change_request])
        self.assertEqual(gate["status"], "REQUIRED_EXTERNAL")
        self.assertEqual(
            gate["reasons"][0]["code"],
            "REVIEW_CHANGES_REQUESTED",
        )

    def test_dismissed_review_invalidates_prior_approval(self) -> None:
        dismissed = copy.deepcopy(BASE_REVIEW)
        dismissed["state"] = "DISMISSED"
        gate = _gate([dismissed])
        self.assertEqual(gate["status"], "REQUIRED_EXTERNAL")
        self.assertEqual(gate["reasons"][0]["code"], "REVIEW_DISMISSED")

    def test_comment_after_approval_does_not_erase_decisive_approval(self) -> None:
        comment = copy.deepcopy(BASE_REVIEW)
        comment["review_id"] = 102
        comment["state"] = "COMMENTED"
        comment["submitted_at"] = "2026-07-05T17:59:30Z"
        gate = _gate([BASE_REVIEW, comment])
        self.assertEqual(gate["status"], "SATISFIED")
        self.assertEqual(gate["receipt"]["review_id"], 101)

    def test_read_permission_is_not_binding(self) -> None:
        review = copy.deepcopy(BASE_REVIEW)
        review["reviewer_permission"] = "read"
        gate = _gate([review])
        self.assertEqual(gate["reasons"][0]["code"], "INSUFFICIENT_PERMISSION")

    def test_self_review_is_not_binding(self) -> None:
        gate = _gate([BASE_REVIEW], author="maintainer")
        self.assertEqual(gate["reasons"][0]["code"], "SELF_REVIEW")

    def test_future_review_is_not_binding(self) -> None:
        review = copy.deepcopy(BASE_REVIEW)
        review["submitted_at"] = "2026-07-05T18:01:00Z"
        gate = _gate([review])
        self.assertEqual(gate["reasons"][0]["code"], "FUTURE_REVIEW")

    def test_review_order_does_not_change_gate_record(self) -> None:
        second = copy.deepcopy(BASE_REVIEW)
        second["review_id"] = 99
        second["reviewer"] = "other-maintainer"
        second["submitted_at"] = "2026-07-05T17:58:00Z"
        second["reviewer_permission"] = "admin"
        first_order = _gate([BASE_REVIEW, second])
        second_order = _gate([second, BASE_REVIEW])
        self.assertEqual(
            first_order["gate_record_id"],
            second_order["gate_record_id"],
        )

    def test_duplicate_review_ids_fail_closed(self) -> None:
        gate = _gate([BASE_REVIEW, BASE_REVIEW])
        self.assertEqual(gate["status"], "NON_RECOMPUTABLE")
        self.assertEqual(gate["reasons"][0]["code"], "INVALID_INPUT")

    def test_receipt_id_tampering_is_rejected(self) -> None:
        gate = _gate([BASE_REVIEW])
        receipt = copy.deepcopy(gate["receipt"])
        receipt["receipt_id"] = "sha256:" + "0" * 64
        with self.assertRaises(ValueError):
            human_review_receipt_id(receipt)


if __name__ == "__main__":
    unittest.main()
