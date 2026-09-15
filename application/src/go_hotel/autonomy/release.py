from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .definitions import ALL_CELL_REGISTRY
from .registry import GovernanceViolation, INDEPENDENT_QA_CELL_ID
from .types import ProductionReality, RiskClass


@dataclass(frozen=True)
class ReleaseEvidence:
    candidate_id: str
    builder_cell: str
    validator_cell: str
    releaser_cell: str
    automated_evaluation_pass: bool
    independent_validation_pass: bool
    policy_gate_pass: bool
    shadow_pass: bool = False
    canary_pass: bool = False
    evidence_refs: Tuple[str, ...] = ()


def authorize_promotion(*, risk_class: RiskClass, evidence: ReleaseEvidence) -> ProductionReality:
    if not isinstance(risk_class, RiskClass):
        raise GovernanceViolation("TYPED_RELEASE_RISK_REQUIRED")
    if not isinstance(evidence, ReleaseEvidence):
        raise GovernanceViolation("TYPED_RELEASE_EVIDENCE_REQUIRED")
    if not isinstance(evidence.candidate_id, str) or not evidence.candidate_id.strip():
        raise GovernanceViolation("RELEASE_CANDIDATE_IDENTITY_REQUIRED")
    actors = (evidence.builder_cell, evidence.validator_cell, evidence.releaser_cell)
    if any(not isinstance(actor, str) or not actor.strip() for actor in actors):
        raise GovernanceViolation("RELEASE_ACTOR_IDENTITY_REQUIRED")
    if any(type(flag) is not bool for flag in (
        evidence.automated_evaluation_pass,
        evidence.independent_validation_pass,
        evidence.policy_gate_pass,
        evidence.shadow_pass,
        evidence.canary_pass,
    )):
        raise GovernanceViolation("RELEASE_FLAGS_MUST_BE_BOOLEAN")
    # Preserve the legacy empty-reference contract, but never accept a scalar
    # string or malformed reference as structured release evidence.
    if not isinstance(evidence.evidence_refs, (tuple, list)) or any(
        not isinstance(ref, str) or not ref.strip() for ref in evidence.evidence_refs
    ):
        raise GovernanceViolation("RELEASE_EVIDENCE_REFERENCES_INVALID")
    if evidence.builder_cell == evidence.validator_cell:
        raise GovernanceViolation("BUILDER_MUST_NOT_EQUAL_VALIDATOR")
    if evidence.validator_cell != INDEPENDENT_QA_CELL_ID:
        raise GovernanceViolation("VALIDATOR_MUST_BE_INDEPENDENT_QA")
    if evidence.releaser_cell == evidence.builder_cell:
        raise GovernanceViolation("BUILDER_MUST_NOT_EQUAL_RELEASER")
    if evidence.releaser_cell == evidence.validator_cell:
        raise GovernanceViolation("VALIDATOR_MUST_NOT_EQUAL_RELEASER")
    for actor in actors:
        ALL_CELL_REGISTRY.cell(actor)
    if risk_class is RiskClass.R4:
        return ProductionReality.PROHIBITED
    if risk_class is RiskClass.R3:
        return ProductionReality.DETERMINISTIC_CONTROLLED
    if not (
        evidence.automated_evaluation_pass
        and evidence.independent_validation_pass
        and evidence.policy_gate_pass
    ):
        return ProductionReality.RESTRICTED
    if risk_class is RiskClass.R2:
        if not evidence.shadow_pass:
            return ProductionReality.SHADOW
        if not evidence.canary_pass:
            return ProductionReality.CANARY
    return ProductionReality.AUTONOMOUS_QUALIFIED
