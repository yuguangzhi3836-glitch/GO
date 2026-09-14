"""C13 independent scope checks; isolated data only, no live supplier or HK access."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func

APP = Path(__file__).resolve().parents[3] / 'application'
sys.path.insert(0, str(APP / 'tests'))

from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import (
    TravelerProfileRow, ProfileConsentRow, ProfileFactRow, ProfileAccessAuditRow,
    JudgmentRuntimeRow, RecommendationDecisionRow, JudgmentEvidencePackageRow,
    OmnichannelMoneyMovementRow, MobilityRefundRow,
)
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault
from go_hotel.travel_intelligence.service import travel_intelligence_service as intelligence
from go_hotel.travel_intelligence import preferences as preferences_module
from go_hotel.judgment.service import judgment_service


def make_owner(tid='c13-self', owner='c13-owner'):
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        session.add(TravelerProfileRow(traveler_id=tid, user_id=owner, full_name='C13 isolated person',
            relationship_type='SELF', nationality='CHN', status='ACTIVE', created_at=now, updated_at=now))
    return tid


def grant(purpose, tid='c13-self', owner='c13-owner'):
    return vault.grant_consent(owner, {'traveler_id':tid, 'consent_type':'EXPLICIT_TRAVEL_PREFERENCE',
        'purpose':purpose, 'scope':['TRAVEL_PREFERENCE:HOTEL_ROOM'],
        'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})['consent_id']


def write(cid, purpose, value, tid='c13-self', owner='c13-owner'):
    return intelligence.save_preference(owner, tid, preference_key='HOTEL_ROOM', value=value,
        purpose=purpose, consent_id=cid, confirmed=True)


def test_c07_two_purpose_withdrawal_does_not_revive_or_remove_other_grant():
    make_owner()
    a, b = grant('BUSINESS_STAY'), grant('FAMILY_HOLIDAY')
    first, second = write(a, 'BUSINESS_STAY', 'quiet'), write(b, 'FAMILY_HOLIDAY', 'connecting')
    vault.revoke_consent('c13-owner', a)
    engine.dispose()
    assert intelligence.preferences('c13-self', purpose='BUSINESS_STAY')['preferences'] == []
    assert intelligence.preferences('c13-self', purpose='FAMILY_HOLIDAY')['preferences'] == [second]
    assert intelligence.traveler_graph('c13-self', purpose='BUSINESS_STAY')['durable_preferences'] == []
    replacement = grant('BUSINESS_STAY')
    assert replacement != a
    assert intelligence.preferences('c13-self', purpose='BUSINESS_STAY')['preferences'] == []
    assert first['preference_id'] != second['preference_id']


def test_c07_foreign_read_and_other_self_id_cannot_access_or_withdraw():
    make_owner(); make_owner('c13-other-self')
    saved = write(grant('STAY'), 'STAY', {'private':'upper floor'})
    with pytest.raises(ValueError, match='TRAVELER_NOT_FOUND'):
        intelligence.preferences('c13-self', purpose='STAY', user_id='c13-attacker')
    with pytest.raises(ValueError, match='TRAVEL_PREFERENCE_NOT_FOUND'):
        intelligence.revoke_preference('c13-owner', 'c13-other-self', saved['preference_id'])
    assert intelligence.preferences('c13-self', purpose='STAY')['preferences'] == [saved]
    assert intelligence.preferences('c13-other-self', purpose='STAY')['preferences'] == []


def test_c07_exact_expiry_is_denied_without_rewriting_preference(monkeypatch):
    make_owner(); cid = grant('STAY'); saved=write(cid, 'STAY', 'private quiet')
    cutoff=datetime(2030,1,1,tzinfo=timezone.utc)
    with SessionLocal.begin() as session:
        consent=session.get(ProfileConsentRow,cid)
        consent.granted_at=cutoff-timedelta(days=1);consent.expires_at=cutoff
    monkeypatch.setattr(preferences_module,'_now',lambda:cutoff-timedelta(microseconds=1))
    assert intelligence.preferences('c13-self',purpose='STAY')['preferences'] == [saved]
    monkeypatch.setattr(preferences_module,'_now',lambda:cutoff)
    assert intelligence.preferences('c13-self',purpose='STAY')['preferences'] == []
    with pytest.raises(ValueError,match='TRAVEL_PREFERENCE_CONSENT_REQUIRED'):
        write(cid,'STAY','private quiet')
    with SessionLocal() as session:
        row=session.get(ProfileFactRow,saved['preference_id'])
        assert row.status=='ACTIVE'
        assert 'private quiet' not in row.value_ciphertext
        audits=session.scalars(select(ProfileAccessAuditRow)).all()
        assert all('private quiet' not in str(row.metadata_json) for row in audits)


def test_c09_rejected_override_preserves_preexisting_active_decision_and_evidence():
    result=judgment_service.reevaluate('c13-hotel')
    with SessionLocal() as session:
        counts=[session.scalar(select(func.count()).select_from(model)) for model in
            (JudgmentRuntimeRow,RecommendationDecisionRow,JudgmentEvidencePackageRow)]
    for extra in ({'completed_review_count':0}, {'confirmed_serious_risk_count':None},
        {'dimension_summary':{}}, {'recommendation_assessment':{'dimensions':{'X':[{'traveler_fit':1}]}}}):
        with pytest.raises(HTTPException) as error:
            judgment_service.reevaluate('c13-hotel',extra)
        assert error.value.status_code==422
    assert judgment_service.get_latest('c13-hotel') == result
    with SessionLocal() as session:
        assert [session.scalar(select(func.count()).select_from(model)) for model in
            (JudgmentRuntimeRow,RecommendationDecisionRow,JudgmentEvidencePackageRow)] == counts


@pytest.mark.parametrize('fault',['duplicate','amount','currency','parent','key'])
def test_c04_bad_actual_receipt_keeps_pending_then_recovers_same_money_once(monkeypatch,fault):
    from tests.test_depth33_mobility_refund_consent import booked
    from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
    from test_depth21_refund_recovery import refunded_movements
    svc,owner,oid=booked('RENTAL')
    quote=svc.refund_quote(owner,oid)
    execute=money.execute_refund_plan
    original={}
    def broken(*args,**kwargs):
        result=execute(*args,**kwargs)
        ids=result['money_movement_ids']
        assert len(ids)==1
        if fault=='duplicate':
            return {**result,'money_movement_ids':ids+ids}
        with SessionLocal.begin() as session:
            row=session.get(OmnichannelMoneyMovementRow,ids[0])
            attr={'amount':'amount_minor','currency':'currency','parent':'parent_movement_id','key':'idempotency_key'}[fault]
            original.update(mid=ids[0],attr=attr,value=getattr(row,attr))
            setattr(row,attr,{'amount':row.amount_minor-1,'currency':'USD','parent':'c13-missing-parent','key':'c13-foreign-operation'}[fault])
        return result
    monkeypatch.setattr(money,'execute_refund_plan',broken)
    with pytest.raises(ValueError):
        svc.cancel(owner,oid,quote['quote_hash'])
    assert svc.get(owner,oid)['status']=='REFUND_PENDING'
    with SessionLocal() as session:
        refund=session.scalar(select(MobilityRefundRow).where(MobilityRefundRow.order_id==oid))
        assert refund.status=='REFUND_PENDING'
    if original:
        with SessionLocal.begin() as session:
            setattr(session.get(OmnichannelMoneyMovementRow,original['mid']),original['attr'],original['value'])
    monkeypatch.setattr(money,'execute_refund_plan',execute)
    result=svc.cancel(owner,oid,quote['quote_hash'])
    assert result['status']=='REFUND_COMPLETED'
    assert svc.cancel(owner,oid,quote['quote_hash'])==result
    assert len(refunded_movements())==1


@pytest.mark.no_db
def test_c12_all_idle_cells_fail_and_reconcile_preserves_original_without_runtime_claims(tmp_path):
    import copy,json
    root=Path(__file__).resolve().parents[3]
    spec=importlib.util.spec_from_file_location('c13_scheduler_validator',root/'ci/round2/validate_ledger.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    ledger=json.loads((root/'ci/round2/example-ledger.json').read_text())
    for cell in ledger['cells']:
        cell['task']['status']='IDLE'; cell['executable_gap']=True;cell['next_task']=None
    before=copy.deepcopy(ledger)
    observed=validator.validate(ledger,tmp_path)
    assert observed['gate']=='SCHEDULER_FAIL'
    assert set(observed['reassign_cells'])=={f'C{i:02d}' for i in range(1,15)}
    after=validator.reconcile(ledger,observed,now='2026-09-14T03:00:00Z')
    assert ledger==before
    assert after['events'][:len(before['events'])]==before['events']
    assert len(after['followups'])==14
    for old,cell in zip(before['cells'],after['cells']):
        assert cell['task_history'][-1]==old['task']
        assert cell['task']['status']=='ASSIGNED'
        assert cell['task']['completion']['percent']==0
        assert all(g['status']=='HOLD' for g in cell['task']['gates'].values())
    assert all(f['acknowledged_at'] is None and f['started_at'] is None for f in after['followups'])
    checked=validator.validate(after,tmp_path)
    assert checked['gate']=='PASS_SCOPED'
    assert validator.reconcile(after,checked,now='2026-09-14T03:01:00Z')==after


@pytest.mark.no_db
def test_c12_digest_alone_does_not_skip_c14_predecessor_or_independent_reviewer(tmp_path):
    import json,hashlib
    root=Path(__file__).resolve().parents[3]
    spec=importlib.util.spec_from_file_location('c13_scheduler_gate_order',root/'ci/round2/validate_ledger.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    ledger=json.loads((root/'ci/round2/example-ledger.json').read_text())
    for cell in ledger['cells']:
        cell['task']['status']='ASSIGNED';cell['executable_gap']=False
    task=ledger['cells'][0]['task']
    (tmp_path/'review.json').write_text('{"synthetic":true}')
    task['evidence']=[{'path':'review.json','sha256':hashlib.sha256((tmp_path/'review.json').read_bytes()).hexdigest(),
        'source_anchor':validator.SOURCE_ANCHOR,'task_id':task['id']}]
    task['status']='DONE_SCOPED';task['completion']['percent']=100
    for name in validator.GATE_NAMES:
        task['gates'][name]={'status':'PASS_SCOPED','evidence_refs':['review.json'],
            'completed_at':'2026-09-14T03:00:00Z','reviewer':'same-person'}
    task['gates']['c14']['completed_at']='2026-09-14T03:00:01Z'
    report=validator.validate(ledger,tmp_path)
    assert report['gate']=='HOLD'
    assert any('independent reviewer' in e for e in report['errors'])
    assert any('timestamp precedes' in e for e in report['errors'])
    task['gates']['c14']['status']='HOLD'
    assert any('passed before predecessors' in e for e in validator.validate(ledger,tmp_path)['errors'])
