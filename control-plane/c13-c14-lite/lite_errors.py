"""Rejection / blocking vocabulary and failure classification.

Two different things are deliberately kept apart:

* ``Reject``  — the record set is *invalid*: tampered, inconsistent, unbound,
  identity-conflicting, expired. Nothing downstream may be derived from it.
* ``Block``   — the record set is *well formed* but not eligible to proceed
  (missing prerequisite, upstream FAIL/BLOCKED, provider/quota failure).

Neither of them is ever a PASS. In particular an AI quota failure must never be
converted into C13 FAIL, C14 FAIL, or a fake PASS (see the task's section 25).
"""
from __future__ import annotations

# --- failure classes (task section 25) ---------------------------------------
QUALITY_FAIL = "QUALITY_FAIL"
RULE_FAIL = "RULE_FAIL"
INFRA_FAILURE = "INFRA_FAILURE"
AI_PROVIDER_FAILURE = "AI_PROVIDER_FAILURE"
AI_QUOTA_EXHAUSTED = "AI_QUOTA_EXHAUSTED"
BLOCKED = "BLOCKED"

FAILURE_CLASSES = (
    QUALITY_FAIL,
    RULE_FAIL,
    INFRA_FAILURE,
    AI_PROVIDER_FAILURE,
    AI_QUOTA_EXHAUSTED,
    BLOCKED,
)

#: Failure class -> the only verdict that class may produce. A quota exhaustion
#: is BLOCKED, never FAIL and never PASS.
FAILURE_CLASS_VERDICT = {
    QUALITY_FAIL: "FAIL",
    RULE_FAIL: "FAIL",
    INFRA_FAILURE: "BLOCKED",
    AI_PROVIDER_FAILURE: "BLOCKED",
    AI_QUOTA_EXHAUSTED: "BLOCKED",
    BLOCKED: "BLOCKED",
}

# --- verdicts ----------------------------------------------------------------
C14_VERDICTS = ("PASS_SCOPED", "FAIL", "BLOCKED", "NOT_APPLICABLE")
C13_VERDICTS = ("PASS_SCOPED", "FAIL", "BLOCKED")

#: C14 terminal states that unlock a C13 acceptance run (task section 19).
C14_PREREQUISITE_OK = ("PASS_SCOPED", "NOT_APPLICABLE")


class Reject(ValueError):
    """Invalid evidence / binding conflict. ``reason`` is a stable machine code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class Block(RuntimeError):
    """Well formed but not eligible to proceed."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def classify_ai_failure(http_status=None, body: str = "", transport_error=None) -> str:
    """Map an AI provider failure to one of the section-25 classes.

    ``You have no credits remaining`` / HTTP 429 with an insufficient-quota
    payload is ``AI_QUOTA_EXHAUSTED`` — the historically observed real failure.
    """
    text = (body or "").lower()
    if transport_error:
        return INFRA_FAILURE
    if "no credits remaining" in text or "insufficient_quota" in text:
        return AI_QUOTA_EXHAUSTED
    if http_status == 429:
        return AI_QUOTA_EXHAUSTED
    if http_status is not None and 500 <= int(http_status) <= 599:
        return AI_PROVIDER_FAILURE
    if http_status == 401 or http_status == 403:
        return AI_PROVIDER_FAILURE
    if http_status is not None and int(http_status) >= 400:
        return AI_PROVIDER_FAILURE
    return AI_PROVIDER_FAILURE
