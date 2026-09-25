"""C13 prerequisite gate (task section 19).

C13 may only form a formal acceptance over a candidate that C14 has already
closed for *the same* candidate SHA. Anything else blocks C13 outright — a C13
PASS must never be produced on top of a FAIL / BLOCKED / missing / mismatched C14.
"""
from __future__ import annotations

from lite_bundle import C14_ROOT_FIELD, verify_root
from lite_errors import Block, C14_PREREQUISITE_OK, Reject

SUCCESS_VERDICTS = tuple(C14_PREREQUISITE_OK)


def _remediation_closed(record) -> bool:
    if record["verdict"] == "NOT_APPLICABLE":
        # No applicable rule set means there is nothing to remediate.
        return True
    return record["remediation_status"] in ("CLOSED", "NOT_REQUIRED")


def evaluate(c14_record, *, candidate_sha: str, now=None) -> dict:
    """Return the sealed C14 summary C13 is allowed to consume.

    Raises ``Reject`` for tampered / mismatched records and ``Block`` when the
    prerequisite is well formed but not admissible.
    """
    if c14_record is None:
        raise Block("c14_record_missing", "C13 cannot run without a sealed C14 record")
    if not isinstance(c14_record, dict):
        raise Reject("c14_record_not_an_object")
    # Recompute the root from the received bytes before believing any field.
    verify_root(c14_record)
    if c14_record["candidate_sha"] != candidate_sha:
        raise Reject("c14_candidate_a_c13_candidate_b")
    verdict = c14_record["verdict"]
    if verdict not in SUCCESS_VERDICTS:
        raise Block("c14_verdict_not_admissible", verdict)
    if not _remediation_closed(c14_record):
        raise Block("c14_remediation_not_closed", str(c14_record.get("remediation_status")))
    return {
        "ok": True,
        "c14_root": c14_record[C14_ROOT_FIELD],
        "c14_verdict": verdict,
        "c14_candidate_sha": c14_record["candidate_sha"],
        "c14_rule_scope_sha256": c14_record["rule_review_scope_sha256"],
        "c14_remediation_closed": True,
    }


def summary_matches(prerequisite: dict, c14_record) -> bool:
    """True when the C14 summary a C13 bundle consumed is the real, sealed one."""
    if not isinstance(prerequisite, dict) or not isinstance(c14_record, dict):
        return False
    return (
        prerequisite.get("c14_root") == c14_record.get(C14_ROOT_FIELD)
        and prerequisite.get("c14_verdict") == c14_record.get("verdict")
        and prerequisite.get("c14_candidate_sha") == c14_record.get("candidate_sha")
        and prerequisite.get("c14_rule_scope_sha256") == c14_record.get("rule_review_scope_sha256")
    )
