"""Independent C13/C14 maker-checker handoff contracts."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from typing import Any
from runtime import Runtime, RuntimeErrorInvariant

@dataclass(frozen=True)
class ReviewRequest:
    source_c: str
    reviewer_c: str
    candidate_sha: str
    application_tree: str
    evidence_ref: str

def _digest(value: dict[str, Any]) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest()

def request_independent_review(rt: Runtime, req: ReviewRequest) -> str:
    if req.reviewer_c not in {"C13","C14"}:
        raise RuntimeErrorInvariant("independent review must target C13 or C14")
    if req.source_c == req.reviewer_c:
        raise RuntimeErrorInvariant("maker and checker identity must differ")
    if not req.candidate_sha or not req.application_tree or not req.evidence_ref:
        raise RuntimeErrorInvariant("candidate binding is incomplete")
    payload={
        "source_c":req.source_c,
        "reviewer_c":req.reviewer_c,
        "candidate_sha":req.candidate_sha,
        "application_tree":req.application_tree,
        "evidence_ref":req.evidence_ref,
    }
    binding=_digest(payload)
    payload["binding_sha256"]=binding
    rt.send_message(req.source_c,req.reviewer_c,"INDEPENDENT_REVIEW_REQUIRED",payload,correlation_id=binding)
    return rt.enqueue(
        req.reviewer_c,"INDEPENDENT_REVIEW",payload,created_by_c=req.source_c,
        priority=10,idempotency_key=f"review:{req.reviewer_c}:{binding}"
    )

def verify_review_binding(payload: dict[str,Any]) -> bool:
    supplied=payload.get("binding_sha256")
    base={k:payload[k] for k in ("source_c","reviewer_c","candidate_sha","application_tree","evidence_ref")}
    return bool(supplied) and supplied == _digest(base)
