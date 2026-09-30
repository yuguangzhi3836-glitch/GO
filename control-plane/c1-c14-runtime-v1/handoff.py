"""Candidate routing for the existing C14 -> C13 independent review channel.

This is a local durable coordination contract. Queue/evidence records do not
replace the formal backend's GitHub readback and execution-independence checks.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from runtime import Runtime, RuntimeErrorInvariant

# Reuse the formal channel's sealed-bundle rules; do not create another verdict
# vocabulary or treat a caller-supplied PASS string as an independent review.
LITE = Path(__file__).resolve().parents[1] / "c13-c14-lite"
if str(LITE) not in sys.path:
    sys.path.insert(0, str(LITE))
from lite_errors import Block, Reject
from lite_prerequisite import evaluate as evaluate_c14


@dataclass(frozen=True)
class ReviewRequest:
    source_c: str
    reviewer_c: str
    candidate_sha: str
    application_tree: str
    evidence_ref: str
    c14_task_id: str | None = None


BASE_FIELDS = ("source_c", "reviewer_c", "candidate_sha", "application_tree", "evidence_ref")
C13_FIELDS = ("c14_task_id", "c14_completion_evidence_id", "c14_prerequisite")


def _digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_review_binding(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or payload.get("reviewer_c") not in {"C13", "C14"}:
        return False
    fields = BASE_FIELDS + (C13_FIELDS if payload["reviewer_c"] == "C13" else ())
    if set(payload) != set(fields) | {"binding_sha256"}:
        return False
    try:
        return bool(payload["binding_sha256"]) and payload["binding_sha256"] == _digest({k: payload[k] for k in fields})
    except (KeyError, TypeError, ValueError):
        return False


def _c14_prerequisite(rt: Runtime, req: ReviewRequest) -> dict:
    if req.source_c != "C14" or not req.c14_task_id:
        raise RuntimeErrorInvariant("C13 requires a completed C14 task")
    if not rt.verify_evidence_chain():
        raise RuntimeErrorInvariant("C14 evidence chain is invalid")
    with rt.tx() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (req.c14_task_id,)).fetchone()
        events = conn.execute("""SELECT * FROM evidence
            WHERE task_id=? AND c_id='C14' AND event_type='TASK_COMPLETED'
            ORDER BY created_at,evidence_id""", (req.c14_task_id,)).fetchall()
    if task is None or task["owner_c"] != "C14" or task["kind"] != "INDEPENDENT_REVIEW" or task["status"] != "SUCCEEDED":
        raise RuntimeErrorInvariant("C14 task is missing or not completed")
    payload = json.loads(task["payload_json"])
    if not verify_review_binding(payload) or payload["reviewer_c"] != "C14":
        raise RuntimeErrorInvariant("C14 task binding is invalid")
    if payload["source_c"] not in {f"C{i}" for i in range(1, 13)}:
        raise RuntimeErrorInvariant("C14 must originate from a builder domain")
    for key in ("candidate_sha", "application_tree", "evidence_ref"):
        if payload[key] != getattr(req, key):
            raise RuntimeErrorInvariant(f"C14 task {key} mismatch")
    if len(events) != 1:
        raise RuntimeErrorInvariant("one C14 completion evidence record is required")
    body = json.loads(events[0]["body_json"])
    if body.get("status") != "SUCCEEDED" or not isinstance(body.get("result"), dict):
        raise RuntimeErrorInvariant("C14 completion evidence is incomplete")
    record = body["result"].get("c14_bundle")
    try:
        prerequisite = evaluate_c14(record, candidate_sha=req.candidate_sha)
    except (Block, Reject) as exc:
        raise RuntimeErrorInvariant(f"C14 prerequisite rejected: {exc}") from exc
    if record["application_tree"] != req.application_tree:
        raise RuntimeErrorInvariant("C14 bundle application_tree mismatch")
    return {"c14_task_id": req.c14_task_id,
            "c14_completion_evidence_id": events[0]["evidence_id"],
            "c14_prerequisite": prerequisite}


def request_independent_review(rt: Runtime, req: ReviewRequest) -> str:
    if req.reviewer_c not in {"C13", "C14"}:
        raise RuntimeErrorInvariant("independent review must target C13 or C14")
    if req.source_c == req.reviewer_c:
        raise RuntimeErrorInvariant("maker and checker identity must differ")
    if not req.candidate_sha or not req.application_tree or not req.evidence_ref:
        raise RuntimeErrorInvariant("candidate binding is incomplete")
    payload = {k: getattr(req, k) for k in BASE_FIELDS}
    if req.reviewer_c == "C14":
        if req.source_c not in {f"C{i}" for i in range(1, 13)} or req.c14_task_id is not None:
            raise RuntimeErrorInvariant("review chain must start at C14 from a builder domain")
    else:
        payload.update(_c14_prerequisite(rt, req))
    binding = _digest(payload)
    payload["binding_sha256"] = binding
    # Keep retrying a validated handoff idempotent at the queue boundary. Messages
    # remain wake notifications; they never constitute review completion.
    task_id = rt.enqueue(req.reviewer_c, "INDEPENDENT_REVIEW", payload,
                         created_by_c=req.source_c, priority=10,
                         idempotency_key=f"review:{req.reviewer_c}:{binding}")
    rt.send_message(req.source_c, req.reviewer_c, "INDEPENDENT_REVIEW_REQUIRED", payload,
                    correlation_id=binding)
    return task_id
