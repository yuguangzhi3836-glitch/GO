from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ReviewSessionRow, RiskEventRuntimeRow, JudgmentHookRow
from go_hotel.security.service import identity_service

def supplier_headers():
    token=identity_service.login('supplier_owner','change-me-supplier');return {'Authorization':'Bearer '+token['access_token']}
def admin_headers():
    token=identity_service.login('go_admin','change-me-admin');return {'Authorization':'Bearer '+token['access_token']}

def risk_decision_headers(client,risk_id):
    identity_service.ensure_user('truth_requester','truth-requester-password','GO_ADMIN',None,['GO_TRUST'])
    identity_service.ensure_user('truth_approver','truth-approver-password','GO_ADMIN',None,['GO_GOVERNANCE'])
    requester={'Authorization':'Bearer '+identity_service.login('truth_requester','truth-requester-password')['access_token']}
    approver={'Authorization':'Bearer '+identity_service.login('truth_approver','truth-approver-password')['access_token']}
    created=client.post('/internal/v1/approvals',headers=requester,json={'operation_type':'RISK_FINALIZATION','subject_type':'RISK_EVENT','subject_id':risk_id,'payload':{}})
    assert created.status_code==200
    approval_id=created.json()['data']['approval_id']
    approved=client.post(f'/internal/v1/approvals/{approval_id}/approve',headers=approver,json={})
    assert approved.status_code==200
    return {**requester,'X-Approval-ID':approval_id}


def booked_order(client, idem='o'):
    ci=(datetime.now(timezone.utc)+timedelta(days=20)).date().isoformat(); co=(datetime.now(timezone.utc)+timedelta(days=24)).date().isoformat()
    s=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':ci,'check_out':co},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'})
    off=s.json()['data']['hotels'][0]['best_offer']
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/orders',headers={'Idempotency-Key':f'ord-{idem}'},json={'prebook_id':pb['prebook_id'],'account_id':'acct_demo'}).json()['data']
    client.post(f"/v1/orders/{o['order_id']}/payments",headers={'Idempotency-Key':f'pay-{idem}'},json={'payment_method_token':'pm_success','amount_minor':o['total_amount_minor'],'currency':'CNY'})
    c=client.post(f"/internal/v1/orders/{o['order_id']}/confirm")
    assert c.status_code==200 and c.json()['data']['status']=='CONFIRMED'
    return o['order_id']


def eligible_review(client, idem='e'):
    oid=booked_order(client,idem)
    d=client.post(f'/internal/v1/orders/{oid}/reviews/eligibility',json={'verified_stay':True}).json()['data']
    return oid,d['review_id']


def test_five_star_one_tap_completes_and_public_score_stays_3_to_5(client):
    _,rid=eligible_review(client,'five')
    client.post(f'/internal/v1/reviews/{rid}/first-invite')
    d=client.post(f'/v1/reviews/{rid}/star',headers={'Idempotency-Key':'five-star'},json={'star':5}).json()['data']
    assert d['status']=='COMPLETED'
    assert d['raw_star_input']==5
    assert 3.0 <= d['experience_score'] <= 5.0
    assert d['risk_candidates']==[]


def test_low_star_requires_structured_tag(client):
    _,rid=eligible_review(client,'lowreq')
    a=client.post(f'/v1/reviews/{rid}/star',json={'star':1})
    assert a.status_code==200 and a.json()['data']['status']=='ELIGIBLE'
    b=client.post(f'/v1/reviews/{rid}/complete')
    assert b.status_code==422
    assert b.json()['detail']['code']=='REVIEW_TAG_REQUIRED'


def test_serious_hygiene_creates_candidate_and_only_maps_relevant_dimension(client):
    _,rid=eligible_review(client,'hyg')
    client.post(f'/v1/reviews/{rid}/star',json={'star':1})
    client.post(f'/v1/reviews/{rid}/tags',json={'tags':['SERIOUS_HYGIENE']})
    client.post(f'/v1/reviews/{rid}/content',json={'text':'Bathroom visibly dirty','photo_refs':['obj://photo-1']})
    d=client.post(f'/v1/reviews/{rid}/complete').json()['data']
    assert d['status']=='COMPLETED'
    assert d['experience_score'] >= 3.0
    assert d['dimension_result']=={'CLEANLINESS':'NEGATIVE'}
    assert len(d['risk_candidates'])==1
    risk=d['risk_candidates'][0]
    assert risk['status']=='CANDIDATE' and risk['risk_type']=='SERIOUS_HYGIENE'
    assert any(x['evidence_type']=='VERIFIED_STAY' for x in risk['evidence'])
    assert any(x['evidence_type']=='PHOTO' for x in risk['evidence'])


def test_supplier_evidence_confirmed_risk_creates_judgment_hook(client):
    _,rid=eligible_review(client,'confirmrisk')
    client.post(f'/v1/reviews/{rid}/star',json={'star':1})
    client.post(f'/v1/reviews/{rid}/tags',json={'tags':['SERIOUS_HYGIENE']})
    risk=client.post(f'/v1/reviews/{rid}/complete').json()['data']['risk_candidates'][0]
    risk_id=risk['risk_event_id']
    s=client.post(f'/v1/supplier/risk-cases/{risk_id}/evidence',headers=supplier_headers(),json={'evidence_type':'HOUSEKEEPING_LOG','payload':{'room':'2801','checked':True}})
    assert s.status_code==200 and s.json()['data']['status']=='UNDER_REVIEW'
    c=client.post(f'/internal/v1/risk-events/{risk_id}/decision',headers=risk_decision_headers(client,risk_id),json={'decision':'CONFIRM','confidence_bps':9000}).json()['data']
    assert c['status']=='CONFIRMED' and c['public_notice'] is not None
    assert len(c['judgment_hooks'])==1
    with SessionLocal() as db:
        assert db.scalar(select(JudgmentHookRow).where(JudgmentHookRow.source_id==risk_id)) is not None


def test_rejected_candidate_does_not_create_judgment_hook(client):
    _,rid=eligible_review(client,'reject')
    client.post(f'/v1/reviews/{rid}/star',json={'star':2})
    client.post(f'/v1/reviews/{rid}/tags',json={'tags':['SAFETY']})
    risk=client.post(f'/v1/reviews/{rid}/complete').json()['data']['risk_candidates'][0]
    r=client.post(f"/internal/v1/risk-events/{risk['risk_event_id']}/decision",headers=risk_decision_headers(client,risk['risk_event_id']),json={'decision':'REJECT','confidence_bps':8500}).json()['data']
    assert r['status']=='REJECTED' and r['judgment_hooks']==[]


def test_remediation_moves_confirmed_risk_to_monitoring_and_rehooks_judgment(client):
    _,rid=eligible_review(client,'rem')
    client.post(f'/v1/reviews/{rid}/star',json={'star':1})
    client.post(f'/v1/reviews/{rid}/tags',json={'tags':['SERIOUS_HYGIENE']})
    risk=client.post(f'/v1/reviews/{rid}/complete').json()['data']['risk_candidates'][0]
    risk_id=risk['risk_event_id']
    client.post(f'/internal/v1/risk-events/{risk_id}/decision',headers=risk_decision_headers(client,risk_id),json={'decision':'CONFIRM'})
    a=client.post(f'/v1/supplier/risk-cases/{risk_id}/remediation',headers=supplier_headers(),json={'action':'Deep clean and supervisor reinspection','evidence_ids':['evd_clean']})
    assert a.json()['data']['status']=='REMEDIATION_REQUIRED'
    v=client.post(f'/internal/v1/risk-events/{risk_id}/verify-remediation',headers=admin_headers()).json()['data']
    assert v['status']=='MONITORING'
    assert len(v['judgment_hooks'])==2


def test_second_trigger_only_for_not_reviewed_and_completed_never_retriggers(client):
    _,rid=eligible_review(client,'second')
    client.post(f'/internal/v1/reviews/{rid}/first-invite')
    client.post(f'/internal/v1/reviews/{rid}/mark-not-reviewed')
    p=client.get('/v1/reviews/pending?account_id=acct_demo').json()['data']
    assert any(x['review_id']==rid for x in p)
    t=client.post(f'/v1/reviews/{rid}/second-trigger').json()['data']
    assert t['status']=='SECOND_TRIGGERED'
    client.post(f'/v1/reviews/{rid}/star',json={'star':5})
    t2=client.post(f'/v1/reviews/{rid}/second-trigger').json()['data']
    assert t2['status']=='COMPLETED'
    p2=client.get('/v1/reviews/pending?account_id=acct_demo').json()['data']
    assert not any(x['review_id']==rid for x in p2)
