from __future__ import annotations

from dataclasses import dataclass

from .complexity import ComplexityAssessment


@dataclass(frozen=True)
class VerificationResult:
    status: str
    deterministic_checks_passed: bool
    model_check_status: str
    execution_allowed: bool
    reasons: tuple[str, ...]


class GOAIVerificationGate:
    """Final GO-owned gate. Model verification is advisory, never transaction truth."""

    def verify(self, *, answer: str, assessment: ComplexityAssessment, model_check_completed: bool) -> VerificationResult:
        reasons: list[str] = []
        deterministic_ok = bool((answer or "").strip())
        if not deterministic_ok:
            reasons.append("EMPTY_SYNTHESIS")
        if assessment.requires_deterministic_gate:
            reasons.append("DETERMINISTIC_AUTHORITY_REQUIRED_FOR_EXECUTION")
        model_status = "COMPLETED" if model_check_completed else "NOT_REQUIRED_OR_UNAVAILABLE"
        execution_allowed = deterministic_ok and not assessment.requires_deterministic_gate
        status = "PASS" if deterministic_ok else "BLOCK"
        if assessment.requires_deterministic_gate and deterministic_ok:
            status = "ADVISORY_ONLY"
        return VerificationResult(status, deterministic_ok, model_status, execution_allowed, tuple(reasons))
