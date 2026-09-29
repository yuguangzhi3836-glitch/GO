"""Execution identity and machine-checked independence (task sections 5 and 21).

``Independent`` here means exactly: *independent AI review execution*. It does not
mean an independent authority, organisation, GitHub account, cloud account, ECS,
HSM, KMS, WIF or registration authority, and nothing in this module may be read as
widening it back to those meanings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lite_errors import Reject

FIELDS = (
    "implementation_execution_id",
    "c13_execution_id",
    "c14_execution_id",
    "c13_github_run_id",
    "c14_github_run_id",
    "c13_nonce",
    "c14_nonce",
)

#: (left, right, reason) — every pair must differ.
DISTINCT_PAIRS = (
    ("implementation_execution_id", "c13_execution_id", "implementation_equals_c13_execution"),
    ("implementation_execution_id", "c14_execution_id", "implementation_equals_c14_execution"),
    ("c13_execution_id", "c14_execution_id", "c13_equals_c14_execution"),
    ("c13_github_run_id", "c14_github_run_id", "c13_run_equals_c14_run"),
    ("c13_nonce", "c14_nonce", "c13_nonce_equals_c14_nonce"),
)


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass
class IndependenceResult:
    ok: bool
    violations: list = field(default_factory=list)

    @property
    def reasons(self):
        return [v["reason"] for v in self.violations]


def check(identities) -> IndependenceResult:
    """Return every independence violation instead of raising on the first one."""
    violations = []
    if not isinstance(identities, dict):
        return IndependenceResult(False, [{"reason": "execution_identities_not_an_object"}])
    for name in FIELDS:
        if not _nonempty(identities.get(name)):
            violations.append({"reason": "execution_identity_missing", "field": name})
    if violations:
        return IndependenceResult(False, violations)
    for left, right, reason in DISTINCT_PAIRS:
        if identities[left] == identities[right]:
            violations.append({"reason": reason, "fields": [left, right]})
    return IndependenceResult(not violations, violations)


def require(identities) -> None:
    """Strict form used on the acceptance path: any violation is a REJECT."""
    result = check(identities)
    if not result.ok:
        raise Reject("execution_independence_violation", ",".join(result.reasons))


def from_bundles(c14_bundle, c13_bundle, *, implementation_execution_id: str) -> dict:
    """Derive the identity set that the chain verifier checks.

    The identities are read from the sealed bundles, not from a document that
    merely *claims* independence.
    """
    return {
        "implementation_execution_id": implementation_execution_id,
        "c13_execution_id": c13_bundle.get("ai_execution_id"),
        "c14_execution_id": c14_bundle.get("ai_execution_id"),
        "c13_github_run_id": str(c13_bundle.get("github_run_id", "")),
        "c14_github_run_id": str(c14_bundle.get("github_run_id", "")),
        "c13_nonce": c13_bundle.get("nonce"),
        "c14_nonce": c14_bundle.get("nonce"),
    }
