"""C14 -> C13 candidate handoff, aligned with the formal Lite V2 channel."""
from __future__ import annotations
from dataclasses import dataclass

from runtime import Runtime
from handoff import ReviewRequest, request_independent_review


@dataclass(frozen=True)
class CandidateBinding:
    candidate_sha: str
    application_tree: str
    evidence_ref: str


class ReviewChain:
    def __init__(self, rt: Runtime):
        self.rt = rt

    def start_c14(self, source_c: str, binding: CandidateBinding) -> str:
        return request_independent_review(self.rt, ReviewRequest(
            source_c, "C14", binding.candidate_sha, binding.application_tree, binding.evidence_ref
        ))

    def advance_to_c13(self, *, c14_task_id: str, binding: CandidateBinding) -> str:
        # No caller-supplied verdict: handoff reads the completed C14 task and
        # validates its stored sealed bundle with the formal prerequisite gate.
        return request_independent_review(self.rt, ReviewRequest(
            "C14", "C13", binding.candidate_sha, binding.application_tree, binding.evidence_ref,
            c14_task_id=c14_task_id
        ))
