"""Real R7 rate-limit shapes; offline clocks and provider doubles only."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from email.utils import format_datetime
import io
import json
import pathlib
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lite_ai_reviewer as ai
import lite_review_batches as batches
import lite_review_pacing as pacing
from test_lite_review_batches import Provider, facts


class Clock:
    def __init__(self):
        self.value = 0.0
        self.waits = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


def rate_error(delay=4.722):
    error = ai.ReviewUnavailable("AI_PROVIDER_FAILURE", "offline rate_limit_exceeded", http_status=429)
    error.rate_limited = True
    error.retry_after_seconds = delay
    return error


class PacingTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.pacer = pacing.ReviewPacer(clock=self.clock.now, sleep=self.clock.sleep)

    def test_all_request_starts_share_the_minimum_gap(self):
        starts = []
        for _ in range(4):
            self.pacer.admit(300)
            starts.append(self.clock.now())
        self.assertEqual(starts, [0, 20, 40, 60])

    def test_provider_backoff_extends_shared_cooldown(self):
        self.pacer.admit(300)
        self.assertTrue(self.pacer.retry(rate_error(45), 0, 300))
        self.pacer.admit(300)
        self.assertEqual(self.clock.now(), 46)

    def test_retry_is_bounded_per_request(self):
        self.assertFalse(self.pacer.retry(rate_error(), pacing.MAX_RETRIES_PER_REQUEST, 300))

    def test_retry_is_bounded_across_the_whole_review(self):
        for _ in range(pacing.MAX_EXTRA_ATTEMPTS):
            self.assertTrue(self.pacer.retry(rate_error(), 0, 300))
        self.assertFalse(self.pacer.retry(rate_error(), 0, 300))

    def test_retry_will_not_outlive_deadline(self):
        self.assertFalse(self.pacer.retry(rate_error(100), 0, 30))

    def test_paced_admission_will_not_outlive_deadline(self):
        self.pacer.admit(10)
        with self.assertRaisesRegex(ai.ReviewUnavailable, "time_budget"):
            self.pacer.admit(10)
        self.assertEqual(self.clock.now(), 0)

    def test_quota_generic_429_auth_and_server_errors_are_not_retried(self):
        for status, failure in ((429, "AI_QUOTA_EXHAUSTED"), (429, "AI_PROVIDER_FAILURE"),
                                (401, "AI_PROVIDER_FAILURE"), (503, "AI_PROVIDER_FAILURE")):
            error = ai.ReviewUnavailable(failure, "offline fixture", http_status=status)
            if failure == "AI_QUOTA_EXHAUSTED":
                error.rate_limited = True  # quota classification still wins
            with self.subTest(status=status, failure=failure):
                self.assertFalse(self.pacer.retry(error, 0, 300))


class ProviderHintTests(unittest.TestCase):
    def failure(self, *, code="rate_limit_exceeded", message="Please try again in 4.722s.", headers=None):
        raw = json.dumps({"error": {"code": code, "message": message}}).encode()
        error = urllib.error.HTTPError(ai.API_URL, 429, "offline fixture", headers or {}, io.BytesIO(raw))
        with patch.object(ai.urllib.request, "urlopen", side_effect=error), self.assertRaises(ai.ReviewUnavailable) as caught:
            ai._call_api(prompt="offline", model="mock", api_key="not-a-key",
                         schema=ai.C14_OUTPUT_SCHEMA, role="c14", timeout=1)
        return caught.exception

    def test_real_r7_seconds_and_milliseconds_are_parsed(self):
        for text, expected in (("Please try again in 4.722s.", 4.722), ("Please try again in 830ms.", .830)):
            error = self.failure(message=text)
            self.assertTrue(error.rate_limited)
            self.assertEqual(error.retry_after_seconds, expected)

    def test_longer_retry_after_header_is_respected(self):
        self.assertEqual(self.failure(headers={"Retry-After": "60"}).retry_after_seconds, 60)

    def test_http_date_retry_after_is_respected(self):
        now = 2_000_000_000
        header = format_datetime(datetime.fromtimestamp(now + 70, timezone.utc), usegmt=True)
        with patch.object(ai.time, "time", return_value=now):
            self.assertEqual(self.failure(headers={"Retry-After": header}).retry_after_seconds, 70)

    def test_missing_hint_uses_conservative_floor(self):
        self.assertEqual(self.failure(message="Rate limit reached").retry_after_seconds, 20)

    def test_invalid_header_does_not_create_infinite_wait(self):
        for value in ("NaN", "Infinity", "-1", "invalid"):
            with self.subTest(value=value):
                self.assertEqual(self.failure(headers={"Retry-After": value}).retry_after_seconds, 4.722)

    def test_insufficient_quota_is_never_treated_as_rate_limit(self):
        error = self.failure(code="insufficient_quota", message="You have no credits remaining")
        self.assertFalse(error.rate_limited)
        self.assertEqual(error.failure_class, "AI_QUOTA_EXHAUSTED")

    def test_unknown_429_is_not_retryable(self):
        self.assertFalse(self.failure(code="unknown").rate_limited)


class PacedIntegrationTests(unittest.TestCase):
    def run_review(self, provider):
        clock = Clock()
        real_pacer = pacing.ReviewPacer
        with patch.object(batches, "MAX_PROMPT_BYTES", 96 * 1024), \
             patch.object(batches, "ReviewPacer", side_effect=lambda: real_pacer(clock=clock.now, sleep=clock.sleep)), \
             patch.object(ai, "_call_api", side_effect=provider):
            return batches.run_partitioned("c14", facts(), model="offline", api_key="not-a-key", timeout=1)

    def test_recovered_rate_limit_is_preserved_and_verified(self):
        provider = Provider()
        attempts = []

        def call(**kwargs):
            attempts.append(kwargs["prompt"])
            if len(attempts) == 1:
                raise rate_error()
            return provider(**kwargs)

        result = self.run_review(call)
        records = result["review_trace"]["parts"]
        self.assertEqual(sum(len(r["rate_limit_retries"]) for r in records), 1)
        with patch.object(batches, "MAX_PROMPT_BYTES", 96 * 1024):
            batches.verify(result, facts=facts())
        self.assertEqual(len(attempts), len(records) + 2)

    def test_persistent_rate_limit_stops_and_preserves_retries(self):
        calls = []

        def call(**kwargs):
            calls.append(kwargs)
            raise rate_error()

        with self.assertRaises(ai.ReviewUnavailable) as caught:
            self.run_review(call)
        trace = caught.exception.review_trace
        self.assertFalse(trace["complete"])
        self.assertIsNone(trace["final"])
        self.assertEqual(len(calls), 2 * (pacing.MAX_RETRIES_PER_REQUEST + 1))
        self.assertTrue(all(len(r["rate_limit_retries"]) == 2 for r in trace["parts"]))

    def test_recovered_retry_survives_later_response_validation_failure(self):
        provider = Provider(bad_json=True)
        calls = []

        def call(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise rate_error()
            return provider(**kwargs)

        with self.assertRaises(ai.ReviewUnavailable) as caught:
            self.run_review(call)
        self.assertEqual(sum(len(r["rate_limit_retries"]) for r in caught.exception.review_trace["parts"]), 1)

    def test_final_rate_failure_retains_earlier_completed_opinions(self):
        provider = Provider()

        def call(**kwargs):
            if "part_id" not in kwargs["schema"]["required"]:
                raise rate_error()
            return provider(**kwargs)

        with self.assertRaises(ai.ReviewUnavailable) as caught:
            self.run_review(call)
        trace = caught.exception.review_trace
        self.assertTrue(all(r["error"] is None for r in trace["parts"]))
        self.assertEqual(len(trace["final_failure"]["rate_limit_retries"]), 2)
        self.assertFalse(trace["complete"])

    def test_whole_review_retry_budget_exhaustion_blocks(self):
        with patch.object(pacing, "MAX_EXTRA_ATTEMPTS", 1), self.assertRaises(ai.ReviewUnavailable) as caught:
            self.run_review(lambda **kwargs: (_ for _ in ()).throw(rate_error()))
        self.assertLessEqual(sum(len(r["rate_limit_retries"]) for r in caught.exception.review_trace["parts"]), 1)

    def test_rehashed_retry_evidence_cannot_exceed_budget(self):
        result = self.run_review(Provider())
        result["review_trace"]["parts"][0]["rate_limit_retries"] = [
            {"http_status": 429, "failure_class": "AI_PROVIDER_FAILURE"}] * 3
        with self.assertRaisesRegex(ai.ReviewUnavailable, "retry_budget"):
            batches.verify(result)


if __name__ == "__main__":
    unittest.main()
