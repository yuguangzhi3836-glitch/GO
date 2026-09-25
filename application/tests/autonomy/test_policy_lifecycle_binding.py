"""Synthetic policy fixtures: no jurisdiction's law or contract is approved here."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from go_hotel.autonomy import (
    ALL_CELL_REGISTRY, AILegalPolicyRegistry, AIActionEnvelope, AuthorityConstitutionGate,
    ConditionEvidence, Environment, LegalDecision, LegalExposureProfile, LegalPolicyRule,
    RiskFactors, action_fingerprint, evaluate_ai_action,
)


NOW = datetime(2026, 9, 25, 8, tzinfo=timezone.utc)


def action(environment=Environment.TEST):
    return AIActionEnvelope("policy-lifecycle", "C02", "FLIGHT_SEARCH", "FLIGHT", environment,
        RiskFactors(0, 0, 0, 0, 0, 0, 0, 0, 0),
        legal_exposure=LegalExposureProfile(consumer_rights=True), jurisdiction="TEST_ONLY")


def rule(**changes):
    values = dict(rule_id="synthetic-consumer-policy", decision=LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS,
        jurisdictions=frozenset({"TEST_ONLY"}), required_exposure_tags=frozenset({"consumer_rights"}),
        conditions=("accepted",), version="fixture-v1", approval_ref="simulation://approved-fixture",
        effective_from=NOW-timedelta(hours=1), effective_until=NOW+timedelta(hours=1))
    values.update(changes)
    return LegalPolicyRule(**values)


def evidence(a, r, **changes):
    values = dict(policy_rule_id=r.rule_id, condition_id="accepted", action_sha256=action_fingerprint(a),
        evidence_ref="simulation://acceptance", observed_at=NOW-timedelta(minutes=1),
        valid_until=NOW+timedelta(hours=2), satisfied=True, policy_sha256=r.policy_sha256)
    values.update(changes)
    return ConditionEvidence(**values)


def decide(a=None, r=None, resolver=None, clock=lambda: NOW, registry=None):
    a, r = a or action(), r or rule()
    return evaluate_ai_action(a, authority_gate=AuthorityConstitutionGate(ALL_CELL_REGISTRY),
        legal_registry=registry or AILegalPolicyRegistry((r,)),
        condition_resolver=resolver or (lambda a, rid, cid: evidence(a, r)), clock=clock)


def test_versioned_fixture_binds_decision_and_condition_to_full_snapshot():
    r = rule()
    result = decide(r=r)
    assert result.executable
    assert result.legal.policy_bindings == ((r.rule_id, r.policy_sha256),)


@pytest.mark.parametrize("environment", [Environment.SHADOW, Environment.STAGING, Environment.CANARY, Environment.PRODUCTION])
def test_legacy_fixture_cannot_authorize_real_environment(environment):
    r = rule(version=None, approval_ref=None, effective_from=None, effective_until=None)
    result = decide(action(environment), r)
    assert not result.executable
    assert result.legal.reason == "LEGAL_POLICY_PROVENANCE_REQUIRED"


@pytest.mark.parametrize("environment", [Environment.DEV, Environment.TEST])
def test_unversioned_isolated_fixture_remains_compatible(environment):
    r = rule(version=None, approval_ref=None, effective_from=None, effective_until=None)
    assert decide(action(environment), r).executable


@pytest.mark.parametrize("changes,reason", [
    ({"effective_from": NOW+timedelta(seconds=1)}, "LEGAL_POLICY_OUTSIDE_VALIDITY_WINDOW"),
    ({"effective_until": NOW}, "LEGAL_POLICY_OUTSIDE_VALIDITY_WINDOW"),
    ({"revoked": True}, "LEGAL_POLICY_REVOKED"),
])
def test_inactive_policy_cannot_be_used(changes, reason):
    result = decide(r=rule(**changes))
    assert not result.executable and result.legal.reason == reason


@pytest.mark.parametrize("changes", [
    {"approval_ref": ""}, {"version": " "}, {"effective_from": None},
    {"effective_until": NOW.replace(tzinfo=None)}, {"effective_from": NOW, "effective_until": NOW},
    {"revoked": "false"},
])
def test_partial_or_malformed_policy_lifecycle_rejected(changes):
    with pytest.raises(ValueError):
        rule(**changes)


@pytest.mark.parametrize("digest", [None, "0"*64])
def test_unbound_or_other_version_condition_is_rejected(digest):
    r = rule()
    result = decide(r=r, resolver=lambda a, rid, cid: evidence(a, r, policy_sha256=digest))
    assert not result.executable and result.blocked_conditions == ((r.rule_id + ":accepted"),)


@pytest.mark.parametrize("changes", [
    {"version": "fixture-v2"}, {"approval_ref": "simulation://other-approval"},
    {"effective_until": NOW+timedelta(hours=2)}, {"reason": "changed terms"},
])
def test_same_id_and_result_cannot_hide_policy_replacement_during_lookup(changes):
    r = rule()
    registry = AILegalPolicyRegistry((r,))
    def resolve(a, rid, cid):
        registry._rules = (replace(r, **changes),)
        return evidence(a, r)
    result = decide(r=r, resolver=resolve, registry=registry)
    assert not result.executable and result.legal.reason == "LEGAL_POLICY_CHANGED_DURING_REVIEW"


@pytest.mark.parametrize("mode", ["expire", "revoke"])
def test_slow_condition_lookup_rechecks_policy_lifetime_and_revocation(mode):
    r = rule()
    registry = AILegalPolicyRegistry((r,))
    ticks = [NOW]
    def resolve(a, rid, cid):
        if mode == "expire":
            ticks[0] = r.effective_until
        else:
            registry._rules = (replace(r, revoked=True),)
        return evidence(a, r)
    result = decide(r=r, resolver=resolve, registry=registry, clock=lambda: ticks[0])
    assert not result.executable and result.legal.reason == "LEGAL_POLICY_CHANGED_DURING_REVIEW"


def test_missing_policy_stays_hold_and_snapshot_does_not_approve_law():
    result = decide(registry=AILegalPolicyRegistry())
    assert not result.executable and result.legal.reason == "NO_APPROVED_LEGAL_POLICY_MATCH"


def test_restrictive_policy_is_not_erased_by_revocation_or_unversioned_allow():
    block = rule(rule_id="restriction", decision=LegalDecision.LEGAL_BLOCK, conditions=(), revoked=True)
    result = decide(registry=AILegalPolicyRegistry((rule(), block)))
    assert not result.executable and result.legal.decision is LegalDecision.LEGAL_BLOCK


def test_wrong_jurisdiction_and_invalid_time_fail_closed():
    assert not decide(replace(action(), jurisdiction="OTHER")).executable
    result = decide(clock=lambda: NOW.replace(tzinfo=None))
    assert not result.executable and result.legal.reason == "POLICY_REVIEW_TIME_REQUIRED"


@pytest.mark.parametrize("environment", [Environment.SHADOW, Environment.STAGING, Environment.CANARY, Environment.PRODUCTION])
def test_versioned_test_policy_cannot_be_borrowed_by_another_environment(environment):
    result = decide(action(environment))
    assert not result.executable and result.legal.reason == "LEGAL_POLICY_ENVIRONMENT_NOT_APPROVED"


@pytest.mark.parametrize("scope", [frozenset(), frozenset({"PRODUCTION"})])
def test_environment_scope_requires_closed_typed_values(scope):
    with pytest.raises(ValueError, match="TYPED_ENVIRONMENT"):
        rule(environments=scope)


def test_environment_scope_is_in_policy_digest():
    r = rule()
    assert r.policy_sha256 != replace(r, environments=frozenset({Environment.TEST})).policy_sha256
