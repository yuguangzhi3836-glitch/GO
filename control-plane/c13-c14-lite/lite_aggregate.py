"""Aggregation: C14 + C13 + ledger binding -> FINAL_ROOT and an eligibility preview.

Two things this module deliberately does **not** do:

* it does not authorise anything — ``authorizes_any_action`` is false everywhere,
  and a ``DEPLOYMENT_ELIGIBLE`` preview is a statement about evidence only;
* it does not implement CC/HK witnesses. Those fields are reserved and null this
  round, so the next round can fill them without a schema change.
"""
from __future__ import annotations

from lite_canonical import digest
from lite_errors import C14_PREREQUISITE_OK, Reject

SCHEMA_VERSION = "go.c13c14.lite.final_root.v1"

WITNESS_FIELDS = ("CC_WITNESS", "HK_WITNESS")


def compute(
    *,
    candidate_sha: str,
    application_tree: str,
    c14_root: str,
    c14_verdict: str,
    c13_root: str,
    c13_verdict: str,
    ledger_binding: dict,
    cc_witness=None,
    hk_witness=None,
) -> dict:
    """FINAL_ROOT over what this round can prove; witnesses stay reserved."""
    body = {
        "schema_version": SCHEMA_VERSION,
        "candidate_sha": candidate_sha,
        "application_tree": application_tree,
        "C14": {"root": c14_root, "verdict": c14_verdict},
        "C13": {"root": c13_root, "verdict": c13_verdict},
        "ledger_binding": ledger_binding,
        "CC_WITNESS": cc_witness,
        "HK_WITNESS": hk_witness,
        "authorizes_any_action": False,
    }
    return {"schema_version": SCHEMA_VERSION, "FINAL_ROOT": digest(body), "body": body}


def preview_eligibility(c14_verdict: str, c13_verdict: str) -> dict:
    """Evidence-only preview of the deployment qualification formula.

    ``DEPLOYMENT_ELIGIBLE`` never means "authorised": a human must still issue the
    deployment instruction, and C13/C14 themselves can never deploy or merge.
    """
    c14_ok = c14_verdict in C14_PREREQUISITE_OK
    c13_ok = c13_verdict == "PASS_SCOPED"
    eligible = bool(c14_ok and c13_ok)
    if not c14_ok and not c13_ok:
        reason = "C14_AND_C13_NOT_ELIGIBLE"
    elif not c14_ok:
        reason = "C14_NOT_ELIGIBLE"
    elif not c13_ok:
        reason = "C13_NOT_PASS_SCOPED"
    else:
        reason = "EVIDENCE_ELIGIBLE"
    return {
        "deployment_eligible": eligible,
        "reason": reason,
        "authorizes_any_action": False,
        "human_authorization_required": True,
    }


def require_witness_slots_absent(cc_witness, hk_witness) -> None:
    """This round must not pretend a witness exists."""
    if cc_witness is not None or hk_witness is not None:
        raise Reject("witness_slots_must_stay_reserved_this_round")
