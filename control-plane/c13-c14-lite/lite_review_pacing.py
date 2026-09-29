"""Shared rate pacing for one cell execution, with finite provider-directed retries."""
from __future__ import annotations

import threading
import time

from lite_ai_reviewer import ReviewUnavailable

REQUEST_START_GAP_SECONDS = 20.0
MAX_RETRIES_PER_REQUEST = 2
MAX_EXTRA_ATTEMPTS = 8


class ReviewPacer:
    def __init__(self, *, clock=None, sleep=None):
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.lock = threading.Lock()
        self.next_start = 0.0
        self.extra_attempts = 0

    def admit(self, deadline):
        with self.lock:
            while True:
                now = self.clock()
                if now >= deadline or self.next_start >= deadline:
                    raise ReviewUnavailable("AI_PROVIDER_FAILURE", "review_time_budget_exceeded")
                delay = self.next_start - now
                if delay <= 0:
                    self.next_start = now + REQUEST_START_GAP_SECONDS
                    return
                self.sleep(min(delay, 1.0))

    def retry(self, error, completed_retries, deadline):
        if not error.rate_limited or error.http_status != 429 or error.failure_class == "AI_QUOTA_EXHAUSTED":
            return False
        if completed_retries >= MAX_RETRIES_PER_REQUEST:
            return False
        delay = max(REQUEST_START_GAP_SECONDS, error.retry_after_seconds or 0.0) + 1.0
        with self.lock:
            if self.extra_attempts >= MAX_EXTRA_ATTEMPTS or self.clock() + delay >= deadline:
                return False
            self.extra_attempts += 1
            self.next_start = max(self.next_start, self.clock() + delay)
        return True
