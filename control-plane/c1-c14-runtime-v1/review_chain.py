"""C13 -> C14 chained independent review state machine."""
from __future__ import annotations
from dataclasses import dataclass
from runtime import Runtime, RuntimeErrorInvariant
from handoff import ReviewRequest, request_independent_review

@dataclass(frozen=True)
class CandidateBinding:
    candidate_sha: str
    application_tree: str
    evidence_ref: str

class ReviewChain:
    def __init__(self, rt: Runtime):
        self.rt=rt

    def start_c13(self, source_c: str, binding: CandidateBinding) -> str:
        return request_independent_review(self.rt, ReviewRequest(
            source_c,"C13",binding.candidate_sha,binding.application_tree,binding.evidence_ref
        ))

    def advance_to_c14(self, *, c13_task_id: str, c13_verdict: str, binding: CandidateBinding) -> str:
        if c13_verdict != "PASS":
            raise RuntimeErrorInvariant("C14 cannot start before C13 PASS")
        payload={
            "c13_task_id":c13_task_id,
            "c13_verdict":c13_verdict,
            "candidate_sha":binding.candidate_sha,
            "application_tree":binding.application_tree,
            "evidence_ref":binding.evidence_ref,
        }
        self.rt.append_evidence("C13",c13_task_id,"C13_PASS_FOR_C14",payload)
        return request_independent_review(self.rt, ReviewRequest(
            "C13","C14",binding.candidate_sha,binding.application_tree,binding.evidence_ref
        ))
