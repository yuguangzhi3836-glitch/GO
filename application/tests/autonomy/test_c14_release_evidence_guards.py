"""C14 regression tests for malformed release input and independent actors.

These are offline promotion decisions, not runtime deployment authorization.
Legacy empty evidence references remain compatible, not proof of acceptance.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from go_hotel.autonomy import (
    GovernanceViolation,
    ProductionReality,
    ReleaseEvidence,
    RiskClass,
    authorize_promotion,
)


def _evidence(**overrides):
    evidence = ReleaseEvidence(
        candidate_id="candidate-c14-guard",
        builder_cell="C01",
        validator_cell="C13",
        releaser_cell="C12",
        automated_evaluation_pass=True,
        independent_validation_pass=True,
        policy_gate_pass=True,
        shadow_pass=True,
        canary_pass=True,
        evidence_refs=("test://c14/source-bound-evidence",),
    )
    return replace(evidence, **overrides)


@pytest.mark.parametrize("risk", [None, "R1", RiskClass.R4.value, 0])
def test_promotion_rejects_untyped_risk_instead_of_falling_through(risk):
    with pytest.raises(GovernanceViolation, match="TYPED_RELEASE_RISK_REQUIRED"):
        authorize_promotion(risk_class=risk, evidence=_evidence())


@pytest.mark.parametrize("evidence", [None, {}, SimpleNamespace(**vars(_evidence()))])
def test_promotion_requires_typed_release_evidence(evidence):
    with pytest.raises(GovernanceViolation, match="TYPED_RELEASE_EVIDENCE_REQUIRED"):
        authorize_promotion(risk_class=RiskClass.R1, evidence=evidence)


@pytest.mark.parametrize("candidate_id", ["", " \t", None, 42])
def test_promotion_requires_nonempty_candidate_identity(candidate_id):
    with pytest.raises(GovernanceViolation, match="RELEASE_CANDIDATE_IDENTITY_REQUIRED"):
        authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(candidate_id=candidate_id))


@pytest.mark.parametrize("field", [
    "automated_evaluation_pass",
    "independent_validation_pass",
    "policy_gate_pass",
    "shadow_pass",
    "canary_pass",
])
@pytest.mark.parametrize("value", ["false", "true", 1, 0, None])
def test_promotion_does_not_treat_coerced_flags_as_pass(field, value):
    with pytest.raises(GovernanceViolation, match="RELEASE_FLAGS_MUST_BE_BOOLEAN"):
        authorize_promotion(risk_class=RiskClass.R2, evidence=_evidence(**{field: value}))


@pytest.mark.parametrize("field", ["builder_cell", "validator_cell", "releaser_cell"])
@pytest.mark.parametrize("value", ["", " \t", None, []])
def test_promotion_rejects_malformed_actor_identity(field, value):
    with pytest.raises(GovernanceViolation, match="RELEASE_ACTOR_IDENTITY_REQUIRED"):
        authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(**{field: value}))


@pytest.mark.parametrize("field", ["builder_cell", "releaser_cell"])
def test_promotion_rejects_unregistered_actor(field):
    with pytest.raises(GovernanceViolation, match="UNKNOWN_CELL:C99"):
        authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(**{field: "C99"}))


def test_validator_must_remain_the_independent_qa_cell():
    with pytest.raises(GovernanceViolation, match="VALIDATOR_MUST_BE_INDEPENDENT_QA"):
        authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(validator_cell="C99"))


def test_validator_cannot_also_be_releaser():
    with pytest.raises(GovernanceViolation, match="VALIDATOR_MUST_NOT_EQUAL_RELEASER"):
        authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(releaser_cell="C13"))


@pytest.mark.parametrize("references", [None, "test://single", {"test://set"}, {"ref": "x"}, ("",), (" \t",), (None,), ("test://valid", 1)])
def test_promotion_rejects_malformed_evidence_references(references):
    with pytest.raises(GovernanceViolation, match="RELEASE_EVIDENCE_REFERENCES_INVALID"):
        authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(evidence_refs=references))


@pytest.mark.parametrize("risk, expected", [
    (RiskClass.R0, ProductionReality.AUTONOMOUS_QUALIFIED),
    (RiskClass.R1, ProductionReality.AUTONOMOUS_QUALIFIED),
    (RiskClass.R2, ProductionReality.AUTONOMOUS_QUALIFIED),
    (RiskClass.R3, ProductionReality.DETERMINISTIC_CONTROLLED),
    (RiskClass.R4, ProductionReality.PROHIBITED),
])
def test_valid_typed_inputs_keep_existing_risk_semantics(risk, expected):
    assert authorize_promotion(risk_class=risk, evidence=_evidence()) is expected


@pytest.mark.parametrize("field", ["automated_evaluation_pass", "independent_validation_pass", "policy_gate_pass"])
def test_false_evaluation_gate_still_restricts_promotion(field):
    assert authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(**{field: False})) is ProductionReality.RESTRICTED


@pytest.mark.parametrize("risk, expected", [
    (RiskClass.R3, ProductionReality.DETERMINISTIC_CONTROLLED),
    (RiskClass.R4, ProductionReality.PROHIBITED),
])
def test_r3_and_r4_hard_boundaries_remain_without_pass_flags_or_references(risk, expected):
    evidence = _evidence(
        automated_evaluation_pass=False,
        independent_validation_pass=False,
        policy_gate_pass=False,
        shadow_pass=False,
        canary_pass=False,
        evidence_refs=(),
    )
    assert authorize_promotion(risk_class=risk, evidence=evidence) is expected


def test_registered_c14_builder_is_not_rejected_as_unknown():
    assert authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(builder_cell="C14")) is ProductionReality.AUTONOMOUS_QUALIFIED


def test_legacy_empty_references_are_preserved_without_claiming_evidence_completeness():
    assert authorize_promotion(risk_class=RiskClass.R1, evidence=_evidence(evidence_refs=())) is ProductionReality.AUTONOMOUS_QUALIFIED


def test_existing_r2_shadow_and_canary_stages_are_unchanged():
    assert authorize_promotion(risk_class=RiskClass.R2, evidence=_evidence(shadow_pass=False, canary_pass=False)) is ProductionReality.SHADOW
    assert authorize_promotion(risk_class=RiskClass.R2, evidence=_evidence(canary_pass=False)) is ProductionReality.CANARY
