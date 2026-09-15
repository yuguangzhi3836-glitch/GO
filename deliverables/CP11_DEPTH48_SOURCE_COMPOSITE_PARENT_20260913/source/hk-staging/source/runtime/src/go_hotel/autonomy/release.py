from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

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
    if evidence.builder_cell == evidence.validator_cell:
        raise GovernanceViolation("BUILDER_MUST_NOT_EQUAL_VALIDATOR")
    if evidence.validator_cell != INDEPENDENT_QA_CELL_ID:
        raise GovernanceViolation("VALIDATOR_MUST_BE_INDEPENDENT_QA")
    if evidence.releaser_cell == evidence.builder_cell:
        raise GovernanceViolation("BUILDER_MUST_NOT_EQUAL_RELEASER")
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
