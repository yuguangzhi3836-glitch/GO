"""Conclude C14 from an unsigned independent AI opinion and real bus evidence.

Machine signature verification remains in house_bridge. It proves provenance,
not reviewer responsibility or deployment authorization. No AI signature here.
"""
import json

from acceptance_gate import Refusal, C14_ENVIRONMENT, _runner
from evidence_time import utc_epoch
from house_bridge import canonical, digest, receive_evidence

FIELDS = {"contract", "role", "reviewer_id", "review_execution_id", "issued_at",
          "review_reference", "opinion", "verdict", "candidate_sha",
          "application_tree", "test_scope_sha256", "task_id", "nonce",
          "evidence_sha256", "receipt_sha256"}


def conclude(task, epoch, host, opinion_reference):
    """Read the independent opinion; never infer one from a green test suite.

    host supplies AIAdmissionHost's review-provenance/readback methods and the
    existing installed bus methods. The trusted recorder captures the actual
    review text and origin before this read, without synthesizing an opinion.
    """
    accepted = receive_evidence(task, epoch, host)
    receipt = accepted["receipt"]
    actor = _runner(host, "C14", receipt["candidate_sha"], C14_ENVIRONMENT)
    reviewer_id, execution_id = host.c14_review_identity()
    if actor != reviewer_id or actor != receipt["runner_id"]:
        raise Refusal("c14_review_identity")
    raw = host.read_review_opinion(opinion_reference)
    if type(raw) is not bytes or not 0 < len(raw) <= 16384:
        raise Refusal("c14_review_bytes")
    try:
        record = json.loads(raw)
        if type(record) is not dict or set(record) != FIELDS or canonical(record) + b"\n" != raw:
            raise Refusal("c14_review_schema")
    except (ValueError, UnicodeError) as exc:
        raise Refusal("c14_review_schema") from exc
    expected = {"contract": "GO_C14_INDEPENDENT_OPINION_V1", "role": "C14",
                "reviewer_id": reviewer_id, "review_execution_id": execution_id,
                **{key: receipt[key] for key in ("task_id", "nonce", "candidate_sha",
                    "application_tree", "test_scope_sha256", "evidence_sha256")},
                "receipt_sha256": digest(canonical(receipt) + b"\n")}
    if any(type(record[key]) is not type(value) or record[key] != value
           for key, value in expected.items()):
        raise Refusal("c14_review_binding")
    if any(type(record[key]) is not str or not record[key].strip()
           for key in ("opinion", "review_reference")):
        raise Refusal("c14_review_opinion")
    reviewed = utc_epoch(record["issued_at"], "c14_review_time")
    if not utc_epoch(receipt["verified_at"], "receipt_time") <= reviewed <= epoch:
        raise Refusal("c14_review_time")
    if record["verdict"] not in ("PASS_SCOPED", "FAIL", "BLOCKED"):
        raise Refusal("c14_review_verdict")
    if record["verdict"] == "PASS_SCOPED" and receipt["verdict"] != "PASS_SCOPED":
        raise Refusal("c14_review_contradicts_tests")
    return {"verdict": record["verdict"], "opinion": record["opinion"],
            "reviewer_id": reviewer_id, "review_reference": record["review_reference"],
            "review_sha256": digest(raw), "receipt": receipt,
            "authorizes_any_action": False}
