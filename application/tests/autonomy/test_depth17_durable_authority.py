"""Merged execution must enforce the current authority rules at commit time."""
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from test_depth08_durable import db_url, make_runtime, submit, effects, qualification
from go_hotel.autonomy import durable
from go_hotel.autonomy.action_control import AILegalPolicyRegistry, LegalPolicyRule
from go_hotel.autonomy.condition_evidence import ConditionEvidence, action_fingerprint
from go_hotel.autonomy.durable import DurableQualifications, transaction, utc_ms
from go_hotel.autonomy.registry import GovernanceViolation
from go_hotel.autonomy.types import LegalDecision, LegalExposureProfile
from go_hotel.db.models import AutonomyQualificationRow as Qualification

pytestmark = pytest.mark.no_db


def register(rt, *, duration=60000, transform=lambda r: r, revision=0):
    record = transform(qualification(next(iter(rt.handlers.values()))))
    with transaction(rt.sessions) as s:
        expiry = durable.db_now_ms(s) + duration
        version = DurableQualifications(s).qualify(record, expires_ms=expiry, expected_revision=revision)
    return record, version


def test_immutable_record_roundtrip_has_explicit_registration_window(db_url):
    rt = make_runtime(db_url, autonomous=True)
    record, version = register(rt)
    assert version == 1
    restarted = make_runtime(db_url, autonomous=True)
    with transaction(restarted.sessions) as s:
        read = DurableQualifications(s).get(record.key)
        assert read.key == record.key and read.evidence == record.evidence
        assert read.valid_from < read.valid_until
        assert read.valid_from.utcoffset() == timedelta(0)
        assert read.metadata == record.metadata
    assert submit(restarted)['status'] == 'QUEUED'
    assert restarted.run_once('a')['status'] == 'SUCCEEDED'


def test_legacy_record_without_window_stays_hold_and_is_not_rewritten(db_url):
    rt = make_runtime(db_url, autonomous=True)
    register(rt)
    with transaction(rt.sessions) as s:
        row = s.scalar(select(Qualification))
        legacy = {k: v for k, v in row.record_json.items() if k not in {'valid_from','valid_until'}}
        row.record_json = legacy
    assert submit(rt)['last_code'] == 'AUTONOMY_QUALIFICATION_VALIDITY_REQUIRED'
    assert rt.run_once('a') is None and effects(rt) == []
    with transaction(rt.sessions) as s:
        assert s.scalar(select(Qualification)).record_json == legacy


def test_revocation_blocks_replaying_same_independent_evidence(db_url):
    rt = make_runtime(db_url, autonomous=True)
    record, version = register(rt)
    with transaction(rt.sessions) as s:
        DurableQualifications(s).revoke(record.key, reason='independent regression', expected_revision=version)
    assert submit(rt)['last_code'] == 'AUTONOMY_NOT_CURRENTLY_QUALIFIED'
    with pytest.raises(GovernanceViolation, match='FRESH_INDEPENDENT_REQUALIFICATION_REQUIRED'):
        register(rt, revision=2)
    with transaction(rt.sessions) as s:
        assert s.scalar(select(Qualification)).revision == 2


def test_new_independent_evidence_can_requalify_after_revocation(db_url, monkeypatch):
    rt = make_runtime(db_url, autonomous=True)
    record, _ = register(rt)
    with transaction(rt.sessions) as s:
        DurableQualifications(s).revoke(record.key, reason='fresh validation needed', expected_revision=1)
    real = durable.db_now_ms
    monkeypatch.setattr(durable, 'db_now_ms', lambda s: real(s) + 1000)
    _, revision = register(rt, revision=2, transform=lambda r: replace(r,
        evidence=replace(r.evidence, evidence_refs=('test://new-independent-validation',))))
    assert revision == 3 and submit(rt)['status'] == 'QUEUED'
    assert rt.run_once('a')['status'] == 'SUCCEEDED'


@pytest.mark.parametrize('corruption,code', [
    ('policy', 'AUTONOMY_QUALIFICATION_POLICY_CHANGED'),
    ('scope', 'QUALIFICATION_INVALID'),
    ('future', 'AUTONOMY_QUALIFICATION_NOT_YET_VALID'),
    ('ttl', 'AUTONOMY_QUALIFICATION_EXPIRED'),
])
def test_persisted_scope_policy_and_time_are_checked(db_url, corruption, code):
    rt = make_runtime(db_url, autonomous=True)
    register(rt)
    with transaction(rt.sessions) as s:
        row = s.scalar(select(Qualification))
        data = dict(row.record_json)
        if corruption == 'policy':
            data['policy_version'] = 'obsolete-policy'
        elif corruption == 'scope':
            data['key'] = {**data['key'], 'environment': 'STAGING'}
        elif corruption == 'future':
            data['valid_from'] = utc_ms(durable.db_now_ms(s) + 10000).isoformat()
        else:
            row.expires_ms = 0
        row.record_json = data
    assert submit(rt)['last_code'] == code
    assert rt.run_once('a') is None and effects(rt) == []


def test_authority_expiring_inside_step_rolls_back_effect_and_checkpoint(db_url, monkeypatch):
    clock = {'advance': 0}
    real = durable.db_now_ms
    monkeypatch.setattr(durable, 'db_now_ms', lambda s: real(s) + clock['advance'])
    def effect(ctx):
        ctx.execute(text('INSERT INTO test_effect VALUES (:id,0,1)'), {'id':ctx.task_id})
        clock['advance'] = 2000
        return {'effect': 1}
    rt = make_runtime(db_url, autonomous=True, steps=(effect,))
    register(rt, duration=1000)
    task = submit(rt)
    result = rt.run_once('a')
    assert result['status'] == 'HOLD' and result['last_code'] == 'AUTONOMY_QUALIFICATION_EXPIRED'
    assert result['next_step'] == 0 and effects(rt) == []
    assert rt.inspect(task['task_id'])['checkpoints'] == []


def conditional(rt):
    rt.legal = AILegalPolicyRegistry((LegalPolicyRule('reviewed-test-policy',
        LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS,
        covered_exposure_tags=frozenset({'money_or_refund'}), conditions=('case-approval',)),))


def proof(rt, action, rule, condition, *, valid_ms=60000):
    with rt.sessions() as s:
        now = durable.db_now_ms(s)
    return ConditionEvidence(rule, condition, action_fingerprint(action), 'test://case-approval',
                             utc_ms(now), utc_ms(now+valid_ms), True)


def test_conditional_execution_persists_bound_evidence_for_each_step(db_url):
    rt = make_runtime(db_url, exposure=LegalExposureProfile(money_or_refund=True), jurisdiction='TEST')
    conditional(rt)
    rt.condition_resolver = lambda a,r,c: proof(rt,a,r,c)
    task = submit(rt, payload={'amount':200})
    assert rt.run_once('a')['status'] == 'SUCCEEDED'
    checks = [e['details'] for e in rt.inspect(task['task_id'])['events'] if e['event_type']=='C14_REVIEW']
    assert len(checks) == 5 and {e['step_no'] for e in checks} == {0,1}
    assert all(e['evidence_refs'] == ['test://case-approval'] and not e['blocked_conditions'] for e in checks)
    assert len({e['request_hash'] for e in checks}) == 1 and all(e['handler_hash'] for e in checks)


@pytest.mark.parametrize('invalid', ['payload', 'step', 'exception'])
def test_wrong_action_or_unavailable_proof_cannot_authorize_effect(db_url, invalid):
    rt = make_runtime(db_url, exposure=LegalExposureProfile(money_or_refund=True), jurisdiction='TEST')
    conditional(rt)
    def resolve(a,r,c):
        if invalid == 'exception':
            raise RuntimeError('verifier unavailable')
        field, value = ('request_hash','different-payload') if invalid=='payload' else ('step_no','99')
        return proof(rt,replace(a, metadata={**a.metadata,field:value}),r,c)
    rt.condition_resolver = resolve
    assert submit(rt)['last_code'] == 'LEGAL_CONDITIONS_UNSATISFIED'
    assert rt.run_once('a') is None and effects(rt) == []


def test_step_zero_proof_cannot_authorize_step_one(db_url):
    rt = make_runtime(db_url, exposure=LegalExposureProfile(money_or_refund=True), jurisdiction='TEST')
    conditional(rt)
    cache = []
    def resolve(a,r,c):
        if not cache:
            cache.append(proof(rt,a,r,c))
        return cache[0]
    rt.condition_resolver = resolve
    submit(rt)
    result = rt.run_once('a')
    assert result['status'] == 'HOLD' and result['last_code']=='LEGAL_CONDITIONS_UNSATISFIED'
    assert result['next_step'] == 1 and len(effects(rt)) == 1


def test_condition_expiring_inside_step_rolls_back_local_effect(db_url, monkeypatch):
    clock = {'advance':0}
    real = durable.db_now_ms
    monkeypatch.setattr(durable, 'db_now_ms', lambda s: real(s)+clock['advance'])
    def effect(ctx):
        ctx.execute(text('INSERT INTO test_effect VALUES (:id,0,1)'), {'id':ctx.task_id})
        clock['advance'] = 2000
        return {'effect':1}
    rt = make_runtime(db_url, steps=(effect,), exposure=LegalExposureProfile(money_or_refund=True), jurisdiction='TEST')
    conditional(rt)
    cache=[]
    def resolve(a,r,c):
        if not cache: cache.append(proof(rt,a,r,c,valid_ms=1000))
        return cache[0]
    rt.condition_resolver = resolve
    submit(rt)
    result = rt.run_once('a')
    assert result['status']=='HOLD' and result['last_code']=='LEGAL_CONDITIONS_UNSATISFIED'
    assert effects(rt)==[] and result['next_step']==0
