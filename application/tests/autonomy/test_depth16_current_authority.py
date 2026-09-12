from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from go_hotel.autonomy import (
    ALL_CELL_REGISTRY, AILegalPolicyRegistry, AIActionEnvelope, AuthorityConstitutionGate,
    AutonomyQualificationRegistry, ConditionEvidence, Environment, GovernanceViolation,
    LegalDecision, LegalExposureProfile, LegalPolicyRule, ProductionReality, RiskClass,
    RiskFactors, action_fingerprint, classify_risk, evaluate_ai_action,
)
from go_hotel.autonomy.types import QualificationEvidence, QualificationKey, QualificationRecord


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def action(**kw):
    values = dict(action_id="current-1", cell_id="C02", capability="FLIGHT_SEARCH", target_domain="FLIGHT",
        environment=Environment.TEST, risk_factors=RiskFactors(0, 1, 0, 0, 0, 0, 0, 0, 0),
        require_autonomous_execution=True)
    values.update(kw)
    return AIActionEnvelope(**values)


def qualification(**kw):
    evidence = QualificationEvidence(True, True, True, True, True, True, True, True, False,
        evidence_refs=("simulation://independent/evaluation-1",))
    values = dict(key=QualificationKey("C02", "FLIGHT_SEARCH", RiskClass.R1, Environment.TEST),
        reality=ProductionReality.AUTONOMOUS_QUALIFIED, evidence=evidence, validator_cell="C13",
        releaser_cell="C12", valid_from=NOW-timedelta(hours=1), valid_until=NOW+timedelta(hours=1))
    values.update(kw)
    return QualificationRecord(**values)


def setup(record=None):
    registry = AutonomyQualificationRegistry(cells=ALL_CELL_REGISTRY)
    registry.qualify(record or qualification())
    return registry, AuthorityConstitutionGate(ALL_CELL_REGISTRY, registry)


def decide(a=None, *, gate=None, rules=(), resolver=None, clock=lambda: NOW):
    return evaluate_ai_action(a or action(), authority_gate=gate or setup()[1],
        legal_registry=AILegalPolicyRegistry(rules), condition_resolver=resolver, clock=clock)


def rule(rid="consumer", tag="consumer_rights", condition="accepted"):
    return LegalPolicyRule(rid, LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS,
        jurisdictions=frozenset({"TEST_ONLY"}), required_exposure_tags=frozenset({tag}), conditions=(condition,))


def exposed(**kw):
    return action(jurisdiction="TEST_ONLY", legal_exposure=LegalExposureProfile(consumer_rights=True), **kw)


def proof(a, rid, cid, **kw):
    values = dict(policy_rule_id=rid, condition_id=cid, action_sha256=action_fingerprint(a),
        evidence_ref=f"simulation://condition/{rid}/{cid}", observed_at=NOW-timedelta(seconds=1),
        valid_until=NOW+timedelta(minutes=1), satisfied=True)
    values.update(kw)
    return ConditionEvidence(**values)


def test_current_independent_qualification_permits_repeated_in_scope_decisions():
    registry, gate = setup()
    assert decide(gate=gate).executable
    assert decide(replace(action(), action_id="current-2"), gate=gate).executable
    assert registry.get(qualification().key).valid_until == NOW+timedelta(hours=1)


@pytest.mark.parametrize("changes,code", [
    ({"valid_from": None, "valid_until": None}, "AUTONOMY_QUALIFICATION_VALIDITY_REQUIRED"),
    ({"valid_from": NOW+timedelta(seconds=1)}, "AUTONOMY_QUALIFICATION_NOT_YET_VALID"),
    ({"valid_until": NOW}, "AUTONOMY_QUALIFICATION_EXPIRED"),
    ({"policy_version": "old-policy"}, "AUTONOMY_QUALIFICATION_POLICY_CHANGED"),
])
def test_missing_or_stale_qualification_is_inspectable_but_cannot_execute(changes, code):
    registry, gate = setup(qualification(**changes))
    result = decide(gate=gate)
    assert not result.executable and result.authority.code == code
    assert registry.get(qualification().key) is not None


@pytest.mark.parametrize("operation", ["suspend", "revoke"])
def test_revocation_takes_effect_on_next_action_and_old_evidence_cannot_requalify(operation):
    registry, gate = setup()
    assert decide(gate=gate).executable
    getattr(registry, operation)(qualification().key, reason="failed_current_evaluation")
    assert not decide(gate=gate).executable
    with pytest.raises(GovernanceViolation, match="FRESH_INDEPENDENT_REQUALIFICATION_REQUIRED"):
        registry.qualify(qualification())
    fresh = replace(qualification(), valid_from=NOW,
        evidence=replace(qualification().evidence, evidence_refs=("simulation://independent/retest-2",)))
    registry.qualify(fresh)
    assert decide(gate=gate).executable


@pytest.mark.parametrize("releaser", [None, "C02", "C13", "unknown"])
def test_actor_and_validator_cannot_release_their_own_qualification(releaser):
    with pytest.raises(GovernanceViolation):
        setup(qualification(releaser_cell=releaser))


@pytest.mark.parametrize("changes", [
    {"valid_until": None}, {"valid_from": NOW.replace(tzinfo=None)},
    {"valid_from": NOW, "valid_until": NOW},
])
def test_invalid_lifetime_is_rejected_without_installing_qualification(changes):
    registry = AutonomyQualificationRegistry(cells=ALL_CELL_REGISTRY)
    with pytest.raises(GovernanceViolation):
        registry.qualify(qualification(**changes))
    assert registry.get(qualification().key) is None


def test_scope_cannot_be_borrowed_from_a_different_environment_or_capability():
    _, gate = setup()
    for changes in [{"environment": Environment.STAGING}, {"capability": "FLIGHT_FARE_RULE"}]:
        result = decide(action(**changes), gate=gate)
        assert not result.executable and result.authority.code == "AUTONOMY_QUALIFICATION_MISSING"


@pytest.mark.parametrize("changes", [
    {"legal_exposure": LegalExposureProfile(money_or_refund=True)},
    {"legal_exposure": LegalExposureProfile(pii_or_identity_use=True)},
    {"truth_mutation": True},
])
def test_material_action_facts_cannot_borrow_zero_money_or_pii_risk_qualification(changes):
    result = decide(action(**changes))
    assert not result.executable and result.authority.risk_class is RiskClass.R2


def test_input_collections_cannot_mutate_an_accepted_action_or_qualification():
    meta = {"target": "offer-1"}; refs = ["simulation://input"]
    a = action(metadata=meta, evidence_refs=refs); fingerprint = action_fingerprint(a)
    meta["target"] = "offer-2"; refs.append("simulation://forged")
    assert action_fingerprint(a) == fingerprint and a.metadata["target"] == "offer-1"
    with pytest.raises(TypeError):
        a.metadata["target"] = "offer-3"
    qmeta = {"evaluation": "passed"}; record = qualification(metadata=qmeta)
    qmeta["evaluation"] = "overwritten"
    assert record.metadata["evaluation"] == "passed"


def test_all_matching_policy_conditions_must_be_verified_with_their_own_rule_binding():
    a = exposed(); rules = (rule(), rule("contract", condition="within_limit"))
    missing = decide(a, rules=rules, resolver=lambda a, r, c: proof(a, r, c) if r == "consumer" else None)
    assert not missing.executable and missing.blocked_conditions == ("contract:within_limit",)
    result = decide(a, rules=rules, resolver=proof)
    assert result.executable
    assert set(result.legal.conditions) == {"accepted", "within_limit"}
    assert len(result.condition_evidence_refs) == 2


def test_same_condition_name_from_different_policies_does_not_share_an_attestation():
    a = exposed(); first = proof(a, "consumer", "accepted")
    result = decide(a, rules=(rule(), rule("contract")), resolver=lambda *args: first)
    assert not result.executable and result.blocked_conditions == ("contract:accepted",)


def test_self_asserted_metadata_or_missing_verifier_never_satisfies_policy_conditions():
    result = decide(exposed(metadata={"accepted": "true", "operation_label": "GREEN"}), rules=(rule(),))
    assert not result.executable and result.blocked_conditions == ("consumer:accepted",)


@pytest.mark.parametrize("changes", [
    {"action_sha256": "0"*64}, {"condition_id": "different"}, {"policy_rule_id": "different"},
    {"valid_until": NOW}, {"observed_at": NOW+timedelta(seconds=1)},
    {"observed_at": NOW.replace(tzinfo=None)}, {"satisfied": "true"}, {"satisfied": False},
    {"evidence_ref": ""},
])
def test_stale_mismatched_or_unproven_condition_cannot_execute(changes):
    result = decide(exposed(), rules=(rule(),), resolver=lambda a, r, c: proof(a, r, c, **changes))
    assert not result.executable and result.blocked_conditions == ("consumer:accepted",)
    assert result.condition_evidence_refs == ()


def test_same_action_id_with_changed_payload_cannot_reuse_a_condition_proof():
    a = exposed(metadata={"offer": "original"}); old = proof(a, "consumer", "accepted")
    changed = replace(a, metadata={"offer": "other"})
    assert not decide(changed, rules=(rule(),), resolver=lambda *args: old).executable


def test_resolver_outage_holds_execution_without_throwing_away_other_policy_conditions():
    def outage(*args):
        raise TimeoutError("unavailable")
    result = decide(exposed(), rules=(rule(),), resolver=outage)
    assert not result.executable and result.blocked_conditions == ("consumer:accepted",)


def test_earlier_proofs_are_checked_again_after_slow_later_condition_lookup():
    ticks = [NOW]
    def resolve(a, r, c):
        result = proof(a, r, c, valid_until=NOW+timedelta(seconds=2 if r == "a" else 30))
        if r == "z": ticks[0] = NOW+timedelta(seconds=3)
        return result
    result = decide(exposed(), rules=(rule("a"), rule("z")), resolver=resolve, clock=lambda: ticks[0])
    assert not result.executable and result.blocked_conditions == ("a:accepted",)


@pytest.mark.parametrize("kind", ["expire", "revoke"])
def test_qualification_is_checked_again_after_condition_lookup(kind):
    registry, gate = setup(); ticks = [NOW]
    def resolve(a, r, c):
        if kind == "expire": ticks[0] = NOW+timedelta(hours=1)
        else: registry.revoke(qualification().key, reason="new_evaluation_failed")
        return proof(a, r, c, valid_until=NOW+timedelta(hours=2))
    result = decide(exposed(), gate=gate, rules=(rule(),), resolver=resolve, clock=lambda: ticks[0])
    assert not result.executable and not result.authority.allowed


def test_policy_replacement_during_condition_lookup_requires_a_fresh_decision():
    registry = AILegalPolicyRegistry((rule(),))
    def resolve(a, r, c):
        registry._rules = (LegalPolicyRule("revoked", LegalDecision.LEGAL_BLOCK),)
        return proof(a, r, c)
    result = evaluate_ai_action(exposed(), authority_gate=setup()[1], legal_registry=registry,
        condition_resolver=resolve, clock=lambda: NOW)
    assert not result.executable and result.legal.reason == "LEGAL_POLICY_CHANGED_DURING_REVIEW"


def test_allow_for_one_exposure_does_not_cover_additional_exposures():
    a = action(require_autonomous_execution=False, jurisdiction="TEST_ONLY",
        legal_exposure=LegalExposureProfile(consumer_rights=True, pii_or_identity_use=True))
    result = decide(a, rules=(rule(),), resolver=proof)
    assert not result.executable and result.legal.reason == "LEGAL_EXPOSURE_NOT_FULLY_COVERED"
    result = decide(a, rules=(rule(), rule("privacy", "pii_or_identity_use", "minimized")), resolver=proof)
    assert result.executable and len(result.condition_evidence_refs) == 2


@pytest.mark.parametrize("decision", [LegalDecision.LEGAL_HOLD, LegalDecision.LEGAL_BLOCK])
def test_restrictive_policy_prevents_condition_lookup_and_execution(decision):
    calls = []
    result = decide(exposed(), rules=(rule(), LegalPolicyRule("restriction", decision)),
        resolver=lambda *args: calls.append(args))
    assert not result.executable and result.legal.decision is decision and calls == []


def test_policy_cannot_remove_external_review_or_ambiguously_duplicate_policy_identity():
    with pytest.raises(ValueError, match="EXTERNAL_POLICY_DECISION_REQUIRED"):
        LegalPolicyRule("bypass", LegalDecision.NOT_REQUIRED)
    with pytest.raises(ValueError, match="CONDITIONAL_POLICY_REQUIRES_CONDITIONS"):
        LegalPolicyRule("empty", LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS)
    with pytest.raises(ValueError, match="DUPLICATE_LEGAL_POLICY_ID"):
        AILegalPolicyRegistry((rule(), rule()))


@pytest.mark.parametrize("factory", [
    lambda: RiskFactors(False, 0, 0, 0, 0, 0, 0, 0, 0),
    lambda: RiskFactors(0.5, 0, 0, 0, 0, 0, 0, 0, 0),
    lambda: RiskFactors(0, 0, 0, 0, 0, 0, 0, 0, 0, prohibited="false"),
    lambda: LegalExposureProfile(money_or_refund="false"),
    lambda: action(environment="PRODUCTION"),
    lambda: action(require_autonomous_execution="false"),
    lambda: replace(qualification().evidence, independent_validation="true"),
])
def test_ambiguous_types_cannot_change_risk_or_environment_semantics(factory):
    with pytest.raises(ValueError): factory()


def test_nonzero_reversibility_is_not_silently_classified_as_local_zero_risk():
    assert classify_risk(RiskFactors(1, 0, 0, 0, 0, 0, 0, 0, 0)) is RiskClass.R1
