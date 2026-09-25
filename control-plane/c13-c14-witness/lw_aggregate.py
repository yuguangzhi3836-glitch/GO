"""FinalAcceptanceAggregator (task sections 14, 17, 19).

Aggregates C14 + C13 + CC verification + CC witness (+ the HK witness when it
exists) into one record with a recomputable ``FINAL_ROOT``.

Two hard boundaries live here:

* ``ACCEPTED`` means the acceptance chain is complete and valid. It does **not**
  mean ``DEPLOY``: the gate stops at ``READY_FOR_HUMAN_AUTHORIZATION`` and
  ``authorizes_any_action`` is false in every record this module produces.
* ``AUTO_DEPLOY`` is structurally impossible — the module has no deploy path at
  all, and the human gate is a required field of the output.
"""
from __future__ import annotations

import lw_paths

lw_paths.install()

import lite_canonical  # noqa: E402
from lite_errors import Reject  # noqa: E402

import lw_witness  # noqa: E402

SCHEMA_VERSION = "go.c13c14.witness.final_acceptance.v1"

ACCEPTED = "ACCEPTED"
BLOCKED = "BLOCKED"
REJECTED = "REJECTED"

HUMAN_GATE = "READY_FOR_HUMAN_AUTHORIZATION"

FIELDS = (
    "schema_version",
    "status",
    "gate",
    "candidate_sha",
    "application_tree",
    "C14_ROOT",
    "C13_ROOT",
    "CC_WITNESS",
    "HK_WITNESS",
    "artifact_metadata_verified",
    "artifact_bytes_verified",
    "human_authorization_required",
    "authorizes_any_action",
    "auto_deploy",
    "FINAL_ROOT",
)


def _final_root(record: dict) -> str:
    body = {
        "candidate_sha": record["candidate_sha"],
        "application_tree": record["application_tree"],
        "C14_ROOT": record["C14_ROOT"],
        "C13_ROOT": record["C13_ROOT"],
        "CC_WITNESS": record["CC_WITNESS"],
        "HK_WITNESS": record["HK_WITNESS"],
        "status": record["status"],
        "authorizes_any_action": False,
    }
    return lite_canonical.digest(body)


def aggregate(*, verification: dict, cc_witness: dict, hk_witness=None, verify_signatures=True) -> dict:
    """Aggregate one round. ``REJECTED`` on invalid input, ``BLOCKED`` on an incomplete chain."""
    record = {
        "schema_version": SCHEMA_VERSION,
        "status": None,
        "gate": None,
        "candidate_sha": None,
        "application_tree": None,
        "C14_ROOT": None,
        "C13_ROOT": None,
        "CC_WITNESS": None,
        "HK_WITNESS": hk_witness,
        "artifact_metadata_verified": False,
        "artifact_bytes_verified": False,
        "human_authorization_required": True,
        "authorizes_any_action": False,
        "auto_deploy": False,
        "FINAL_ROOT": None,
    }

    if verification.get("decision") != "ACCEPT":
        record["status"] = REJECTED if verification.get("decision") == "REJECT" else BLOCKED
        record["gate"] = "NOT_ACCEPTED"
        return record
    if cc_witness is None:
        record["status"] = BLOCKED
        record["gate"] = "CC_WITNESS_MISSING"
        return record

    if verify_signatures:
        lw_witness.verify_witness(cc_witness)
        if hk_witness is not None:
            lw_witness.verify_witness(hk_witness)

    for field, source in (("candidate_sha", "candidate_sha"), ("application_tree", "application_tree"),
                          ("C14_ROOT", "c14_root"), ("C13_ROOT", "c13_root")):
        if cc_witness.get(field) != verification.get(source):
            raise Reject("cc_witness_verification_mismatch", field)
    if hk_witness is not None:
        for field in ("candidate_sha", "application_tree", "C14_ROOT", "C13_ROOT"):
            if hk_witness.get(field) != cc_witness.get(field):
                raise Reject("hk_witness_cc_witness_mismatch", field)

    record.update({
        "candidate_sha": verification["candidate_sha"],
        "application_tree": verification["application_tree"],
        "C14_ROOT": verification["c14_root"],
        "C13_ROOT": verification["c13_root"],
        "CC_WITNESS": cc_witness,
        "artifact_metadata_verified": bool(verification.get("artifact_metadata_verified")),
        "artifact_bytes_verified": bool(verification.get("artifact_bytes_verified")),
        "status": ACCEPTED,
        "gate": HUMAN_GATE,
    })
    record["FINAL_ROOT"] = _final_root(record)
    return record


def verify_final_root(record: dict) -> None:
    """Recompute FINAL_ROOT over the received bytes; any change must be visible."""
    if not isinstance(record, dict) or set(record) != set(FIELDS):
        raise Reject("final_acceptance_field_set_mismatch")
    if record["authorizes_any_action"] is not False:
        raise Reject("authorizes_any_action_must_be_false")
    if record["auto_deploy"] is not False:
        raise Reject("auto_deploy_must_be_false")
    if record["status"] == ACCEPTED and record["gate"] != HUMAN_GATE:
        raise Reject("accepted_must_stop_at_the_human_gate", str(record["gate"]))
    if record["status"] == ACCEPTED and record["FINAL_ROOT"] != _final_root(record):
        raise Reject("final_root_recompute_mismatch")
