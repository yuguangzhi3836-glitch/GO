from __future__ import annotations

from dataclasses import dataclass

from .types import RiskClass


@dataclass(frozen=True)
class RiskFactors:
    reversibility: int
    blast_radius: int
    money_exposure: int
    pii_exposure: int
    truth_mutation: int
    customer_impact: int
    supplier_impact: int
    regulatory_impact: int
    cross_domain_impact: int
    prohibited: bool = False
    constitutional_boundary: bool = False
    security_boundary: bool = False
    financial_boundary: bool = False

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if name in {
                "prohibited",
                "constitutional_boundary",
                "security_boundary",
                "financial_boundary",
            }:
                continue
            if not 0 <= value <= 3:
                raise ValueError(f"RISK_FACTOR_OUT_OF_RANGE:{name}")


def classify_risk(factors: RiskFactors) -> RiskClass:
    """Deterministic minimum classification; callers cannot self-declare lower risk."""
    if factors.prohibited:
        return RiskClass.R4
    if factors.constitutional_boundary or factors.security_boundary or factors.financial_boundary:
        return RiskClass.R3
    material = (
        factors.money_exposure >= 2
        or factors.pii_exposure >= 2
        or factors.truth_mutation >= 2
        or factors.regulatory_impact >= 2
        or factors.cross_domain_impact >= 2
        or factors.blast_radius >= 3
        or factors.customer_impact >= 3
        or factors.supplier_impact >= 3
    )
    if material:
        return RiskClass.R2
    bounded = any(
        value > 0
        for value in (
            factors.blast_radius,
            factors.money_exposure,
            factors.pii_exposure,
            factors.truth_mutation,
            factors.customer_impact,
            factors.supplier_impact,
            factors.regulatory_impact,
            factors.cross_domain_impact,
        )
    )
    return RiskClass.R1 if bounded else RiskClass.R0
