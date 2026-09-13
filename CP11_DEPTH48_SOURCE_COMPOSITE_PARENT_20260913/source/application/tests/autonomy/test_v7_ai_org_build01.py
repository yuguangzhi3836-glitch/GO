import pytest

from go_hotel.autonomy import (
    AutonomyQualificationRegistry,
    CELLS,
    DOMAIN_OWNERSHIP,
    Environment,
    GovernanceViolation,
    ProductionReality,
    ReleaseEvidence,
    RiskFactors,
    RiskClass,
    authorize_promotion,
    classify_risk,
)
from go_hotel.autonomy.types import QualificationEvidence, QualificationKey, QualificationRecord


def _evidence(**overrides):
    data = dict(
        evaluation=True,
        historical_evidence=True,
        boundary_tests=True,
        failure_tests=True,
        security_tests=True,
        confidence_calibration=True,
        rollback_capability=True,
        independent_validation=True,
        production_evidence=True,
        evidence_refs=("test://build01",),
    )
    data.update(overrides)
    return QualificationEvidence(**data)


def test_exactly_13_permanent_cells_and_unique_domain_final_owner():
    assert len(CELLS) == 13
    assert len(DOMAIN_OWNERSHIP.cells) == 13
    assert len({c.domain for c in CELLS}) == 13
    assert DOMAIN_OWNERSHIP.owner_for("GO_AI_PLAN").truth_owned == "PLAN"
    assert DOMAIN_OWNERSHIP.owner_for("UNIFIED_TRIPS").truth_owned == "JOURNEY_TRUTH"
    assert DOMAIN_OWNERSHIP.owner_for("TRANSACTION_FINANCE").truth_owned == "TRANSACTION_TRUTH"
    assert DOMAIN_OWNERSHIP.owner_for("GO_JUDGMENT").truth_owned == "RECOMMENDATION_TRUTH"


def test_no_cross_domain_truth_mutation():
    DOMAIN_OWNERSHIP.assert_truth_write(actor_cell="C02", target_domain="FLIGHT")
    with pytest.raises(GovernanceViolation, match="CROSS_DOMAIN_TRUTH_MUTATION_DENIED"):
        DOMAIN_OWNERSHIP.assert_truth_write(actor_cell="C08", target_domain="FLIGHT")


def test_risk_engine_is_deterministic_and_r3_r4_are_hard_boundaries():
    assert classify_risk(RiskFactors(0, 0, 0, 0, 0, 0, 0, 0, 0)) is RiskClass.R0
    assert classify_risk(RiskFactors(3, 1, 0, 0, 0, 1, 0, 0, 0)) is RiskClass.R1
    assert classify_risk(RiskFactors(1, 3, 0, 0, 0, 1, 0, 0, 0)) is RiskClass.R2
    assert classify_risk(RiskFactors(0, 0, 0, 0, 0, 0, 0, 0, 0, financial_boundary=True)) is RiskClass.R3
    assert classify_risk(RiskFactors(0, 0, 0, 0, 0, 0, 0, 0, 0, prohibited=True)) is RiskClass.R4


def test_builder_cannot_self_certify_or_release():
    with pytest.raises(GovernanceViolation, match="BUILDER_MUST_NOT_EQUAL_VALIDATOR"):
        authorize_promotion(
            risk_class=RiskClass.R1,
            evidence=ReleaseEvidence("cand-1", "C01", "C01", "C13", True, True, True),
        )
    with pytest.raises(GovernanceViolation, match="BUILDER_MUST_NOT_EQUAL_RELEASER"):
        authorize_promotion(
            risk_class=RiskClass.R1,
            evidence=ReleaseEvidence("cand-2", "C01", "C13", "C01", True, True, True),
        )


def test_r2_requires_shadow_then_canary_before_autonomous_qualified():
    base = dict(candidate_id="c", builder_cell="C01", validator_cell="C13", releaser_cell="C12", automated_evaluation_pass=True, independent_validation_pass=True, policy_gate_pass=True)
    assert authorize_promotion(risk_class=RiskClass.R2, evidence=ReleaseEvidence(**base)) is ProductionReality.SHADOW
    assert authorize_promotion(risk_class=RiskClass.R2, evidence=ReleaseEvidence(**base, shadow_pass=True)) is ProductionReality.CANARY
    assert authorize_promotion(risk_class=RiskClass.R2, evidence=ReleaseEvidence(**base, shadow_pass=True, canary_pass=True)) is ProductionReality.AUTONOMOUS_QUALIFIED


def test_r3_is_deterministic_controlled_and_r4_prohibited():
    evidence = ReleaseEvidence("c", "C01", "C13", "C12", True, True, True, True, True)
    assert authorize_promotion(risk_class=RiskClass.R3, evidence=evidence) is ProductionReality.DETERMINISTIC_CONTROLLED
    assert authorize_promotion(risk_class=RiskClass.R4, evidence=evidence) is ProductionReality.PROHIBITED


def test_production_qualification_fails_closed_until_legal_accountability_is_bound():
    registry = AutonomyQualificationRegistry(cells=DOMAIN_OWNERSHIP)
    record = QualificationRecord(
        key=QualificationKey("C01", "HOTEL_ENTITY", RiskClass.R1, Environment.PRODUCTION),
        reality=ProductionReality.AUTONOMOUS_QUALIFIED,
        evidence=_evidence(),
        validator_cell="C13",
        releaser_cell="C12",
    )
    with pytest.raises(GovernanceViolation, match="LEGAL_ACCOUNTABILITY_NOT_BOUND"):
        registry.qualify(record)
    assert len(DOMAIN_OWNERSHIP.production_accountability_gaps()) == 13


def test_qualification_is_cell_capability_risk_environment_scoped_and_revocable():
    registry = AutonomyQualificationRegistry(cells=DOMAIN_OWNERSHIP)
    key = QualificationKey("C02", "FLIGHT_SEARCH", RiskClass.R1, Environment.STAGING)
    record = QualificationRecord(key, ProductionReality.AUTONOMOUS_QUALIFIED, _evidence(), "C13", "C12")
    registry.qualify(record)
    assert registry.get(key).reality is ProductionReality.AUTONOMOUS_QUALIFIED
    revoked = registry.revoke(key, reason="EVALUATION_REGRESSION")
    assert revoked.reality is ProductionReality.RESTRICTED
    assert revoked.metadata["revocation_reason"] == "EVALUATION_REGRESSION"


def test_go_ai_does_not_own_journey_transaction_or_recommendation_truth():
    go_ai = DOMAIN_OWNERSHIP.cell("C08")
    assert {"JOURNEY_TRUTH_MUTATION", "TRANSACTION_TRUTH_MUTATION", "RECOMMENDATION_TRUTH_MUTATION"} <= go_ai.forbidden_capabilities
