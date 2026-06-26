import unittest

from ibex_agent_verification.inference_evidence import (
    InferenceEvidenceError,
    analyze_capture,
)


class ProviderThroughputTests(unittest.TestCase):
    def base_events(self):
        return [
            {"event": "request_start", "monotonic_ns": 1_000_000_000},
            {
                "event": "response_headers",
                "monotonic_ns": 1_050_000_000,
                "status_code": 200,
            },
            {
                "event": "chunk",
                "monotonic_ns": 1_326_000_000,
                "payload": {
                    "choices": [{"delta": {"reasoning": "thinking"}}],
                },
            },
            {
                "event": "chunk",
                "monotonic_ns": 1_326_947_100,
                "payload": {
                    "choices": [{"delta": {"content": "Hello there"}}],
                },
            },
            {
                "event": "chunk",
                "monotonic_ns": 1_327_774_979,
                "payload": {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 73,
                        "completion_tokens": 63,
                        "total_tokens": 136,
                        "completion_tokens_details": {"reasoning_tokens": 51},
                    },
                    "time_info": {
                        "queue_time": 0.00404292,
                        "prompt_time": 0.00252575,
                        "completion_time": 0.03302387,
                        "total_time": 0.04209184646606445,
                    },
                },
            },
            {"event": "request_end", "monotonic_ns": 1_328_364_792},
        ]

    def test_prefers_provider_completion_time_over_visible_text_interval(self):
        result = analyze_capture(
            self.base_events(), provider="cerebras", model="gpt-oss-120b"
        )

        self.assertEqual(result["status"], "COMPLETE")
        self.assertAlmostEqual(
            result["throughput"]["output_tokens_per_second"],
            63 / 0.03302387,
            places=9,
        )
        self.assertEqual(
            result["throughput"]["source"], "provider_usage_and_time_info"
        )
        self.assertEqual(result["usage"]["reasoning_tokens"], 51)
        self.assertEqual(
            result["timing"]["provider_reported_seconds"]["completion_time"],
            0.03302387,
        )

    def test_reasoning_tokens_without_provider_time_refuse_misleading_rate(self):
        events = self.base_events()
        events[4]["payload"].pop("time_info")

        result = analyze_capture(events, provider="cerebras", model="gpt-oss-120b")

        self.assertIsNone(result["throughput"]["output_tokens_per_second"])
        self.assertIsNone(result["throughput"]["source"])
        self.assertEqual(
            result["throughput"]["unavailable_reason"],
            "reasoning_tokens_without_provider_completion_time",
        )

    def test_invalid_provider_time_is_rejected(self):
        events = self.base_events()
        events[4]["payload"]["time_info"]["completion_time"] = -1

        with self.assertRaisesRegex(InferenceEvidenceError, "finite non-negative"):
            analyze_capture(events, provider="cerebras", model="gpt-oss-120b")

    def test_positive_tokens_require_positive_provider_completion_time(self):
        events = self.base_events()
        events[4]["payload"]["time_info"]["completion_time"] = 0

        with self.assertRaisesRegex(InferenceEvidenceError, "must be positive"):
            analyze_capture(events, provider="cerebras", model="gpt-oss-120b")


if __name__ == "__main__":
    unittest.main()
