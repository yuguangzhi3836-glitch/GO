from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JudgmentHookRow, JudgmentRuntimeRow, RecommendationDecisionRow, RiskEventRuntimeRow


def booked_order(client, idem='j'):
    ci=(datetime.now(timezone.utc)+timedelta(days=30)).date().isoformat(); co=(datetime.now(timezone.utc)+timedelta(days=34)).date().isoformat()
    s=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':ci,'check_out':co},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'})
    off=s.json()['data']['hotels'][0]['best_offer']; hotel_id=s.json()['data']['hotels'][0]['hotel_id']
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/orders',headers={'Idempotency-Key':f'ord-jud-{idem}'},json={'prebook_id':pb['prebook_id'],'account_id':'acct_demo'}).json()['data']
    client.post(f"/v1/orders/{o['order_id']}/payments",headers={'Idempotency-Key':f'pay-jud-{idem}'},json={'payment_method_token':'pm_success','amount_minor':o['total_amount_minor'],'currency':'CNY'})
    client.post(f"/internal/v1/orders/{o['order_id']}/confirm")
    return o['order_id'],hotel_id


def review(client, idem='j', star=5, tags=None):
    oid,hid=booked_order(client,idem)
    r=client.post(f'/internal/v1/orders/{oid}/reviews/eligibility',json={'verified_stay':True}).json()['data']
    rid=r['review_id']; client.post(f'/v1/reviews/{rid}/star',json={'star':star})
    if tags: client.post(f'/v1/reviews/{rid}/tags',json={'tags':tags})
    if star<=3 or tags: client.post(f'/v1/reviews/{rid}/complete')
    return hid,rid


def test_high_go_score_does_not_auto_create_recommendation(client):
    hid,_=review(client,'good',5)
    d=client.post(f'/internal/v1/judgments/{hid}/reevaluate',json={}).json()['data']
    assert d['judgment_id'].startswith('jud_')
    assert d['evidence_package']['package_id'].startswith('evpkg_')
    assert len(d['evidence_package']['content_hash'])==64
    assert d['recommendation']['status']=='NOT_YET_RATED'
    assert 'RECOMMENDATION_ASSESSMENT_REQUIRED' in d['recommendation']['reason_codes']
    assert d['public_go_score'] is None
    assert 'commercial_revenue' in d['evidence_package']['excluded_commercial_fields']


def test_commercial_fields_physically_rejected_from_judgment(client):
    hid,_=review(client,'commercial',5)
    r=client.post(f'/internal/v1/judgments/{hid}/reevaluate',json={'extra_features':{'commercial_revenue':999999}})
    assert r.status_code==422
    assert r.json()['detail']['code']=='JUDGMENT_COMMERCIAL_FIELD_FORBIDDEN'



def risk_decision_headers(client,risk_id):
    from go_hotel.security.service import identity_service
    identity_service.ensure_user('wave_trust','wave-trust-password','GO_ADMIN',None,['GO_TRUST'])
    identity_service.ensure_user('wave_approver','wave-approver-password','GO_ADMIN',None,['GO_GOVERNANCE'])
    req=client.post('/v1/auth/login',json={'username':'wave_trust','password':'wave-trust-password'}).json()['data']['access_token']
    app=client.post('/v1/auth/login',json={'username':'wave_approver','password':'wave-approver-password'}).json()['data']['access_token']
    req_h={'Authorization':'Bearer '+req}; app_h={'Authorization':'Bearer '+app}
    ar=client.post('/internal/v1/approvals',headers=req_h,json={'operation_type':'RISK_FINALIZATION','subject_type':'RISK_EVENT','subject_id':risk_id,'payload':{}})
    assert ar.status_code==200
    aid=ar.json()['data']['approval_id']
    approved=client.post(f'/internal/v1/approvals/{aid}/approve',headers=app_h,json={})
    assert approved.status_code==200
    return {**req_h,'X-Approval-ID':aid}

def login_headers(client,username,password):
    r=client.post('/v1/auth/login',json={'username':username,'password':password})
    assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['data']['access_token']}

def test_confirmed_serious_risk_rehooks_and_moves_to_not_recommended(client):
    hid,rid=review(client,'risk',1,['SERIOUS_HYGIENE'])
    with SessionLocal() as s:
        risk_id=s.scalar(select(RiskEventRuntimeRow.risk_event_id).where(RiskEventRuntimeRow.review_id==rid))
    r=client.post(f'/internal/v1/risk-events/{risk_id}/decision',headers=risk_decision_headers(client,risk_id),json={'decision':'CONFIRM','confidence_bps':9300}); assert r.status_code==200
    with SessionLocal() as s:
        hook=s.scalar(select(JudgmentHookRow).where(JudgmentHookRow.source_id==risk_id,JudgmentHookRow.status=='REQUESTED'))
        hook_id=hook.hook_id
    d=client.post(f'/internal/v1/judgment-hooks/{hook_id}/process').json()['data']
    assert d['recommendation']['status']=='GO_NOT_RECOMMENDED'
    assert d['public_go_score'] is None
    assert 'CONFIRMED_SERIOUS_RISK' in d['explanation']['why_recommended_or_not']


def test_remediation_creates_new_judgment_and_replayable_history(client):
    hid,rid=review(client,'remed',1,['SERIOUS_HYGIENE'])
    with SessionLocal() as s:
        risk_id=s.scalar(select(RiskEventRuntimeRow.risk_event_id).where(RiskEventRuntimeRow.review_id==rid))
    r=client.post(f'/internal/v1/risk-events/{risk_id}/decision',headers=risk_decision_headers(client,risk_id),json={'decision':'CONFIRM'}); assert r.status_code==200
    client.post('/internal/v1/judgment-hooks/process-pending')
    first_pub=client.get(f'/v1/hotels/{hid}/judgment').json()['data']
    first=client.get(f"/internal/v1/judgments/{first_pub['judgment_id']}").json()['data']
    r=client.post(f'/v1/supplier/risk-cases/{risk_id}/remediation',headers=login_headers(client,'supplier_owner','change-me-supplier'),json={'action':'Deep clean + supervisor audit','evidence_ids':['evd_fix']}); assert r.status_code==200
    r=client.post(f'/internal/v1/risk-events/{risk_id}/verify-remediation',headers=login_headers(client,'wave_trust','wave-trust-password')); assert r.status_code==200
    client.post('/internal/v1/judgment-hooks/process-pending')
    second_pub=client.get(f'/v1/hotels/{hid}/judgment').json()['data']
    second=client.get(f"/internal/v1/judgments/{second_pub['judgment_id']}").json()['data']
    assert second['judgment_id'] != first['judgment_id']
    assert second['evidence_package']['content_hash'] != first['evidence_package']['content_hash']
    old=client.get(f"/internal/v1/judgments/{first['judgment_id']}").json()['data']
    assert old['status']=='SUPERSEDED'
    with SessionLocal() as s:
        assert s.scalar(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.judgment_id==second['judgment_id'])) is not None
        assert s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==second['judgment_id'])) is not None


def test_raw_star_not_in_feature_snapshot(client):
    hid,_=review(client,'nostar',5)
    d=client.post(f'/internal/v1/judgments/{hid}/reevaluate',json={}).json()['data']
    feature=d['evidence_package']['feature_snapshot']
    assert 'raw_star_input' not in feature and 'user_rating' not in feature


def constitution_assessment(verdict='GO_RECOMMENDED',worth='YES'):
    return {
        'verdict':verdict,
        'worth_the_journey':worth,
        'commercial_independence_attested':True,
        'dimensions':{k:{'state':'PRESENT','evidence_summary':f'Independent evidence for {k}'} for k in (
            'WORK_OF_HOSPITALITY','IRREPLACEABILITY','SENSE_OF_PLACE','AESTHETIC_JUDGMENT','EMOTIONAL_RESONANCE','WORTH_THE_JOURNEY'
        )}
    }

def test_constitution_assessment_can_publish_go_recommended_without_score_threshold_rule(client):
    hid,_=review(client,'constitution',5)
    d=client.post(f'/internal/v1/judgments/{hid}/reevaluate',json={'extra_features':{'recommendation_assessment':constitution_assessment()}}).json()['data']
    assert d['recommendation']['status']=='GO_RECOMMENDED'
    assert 'GO_RECOMMENDATION_CONSTITUTION_PASSED' in d['recommendation']['reason_codes']
    assert d['public_go_score']==d['go_score']

def test_worth_the_journey_yes_is_mandatory_for_recommendation(client):
    hid,_=review(client,'worth',5)
    d=client.post(f'/internal/v1/judgments/{hid}/reevaluate',json={'extra_features':{'recommendation_assessment':constitution_assessment(worth='NO')}}).json()['data']
    assert d['recommendation']['status']=='NOT_YET_RATED'
    assert 'WORTH_THE_JOURNEY_EXPLICIT_YES_REQUIRED' in d['recommendation']['reason_codes']

def test_nested_commercial_field_is_rejected_from_recommendation_assessment(client):
    hid,_=review(client,'nested-commercial',5)
    a=constitution_assessment(); a['dimensions']['WORK_OF_HOSPITALITY']['commission']=0.03
    r=client.post(f'/internal/v1/judgments/{hid}/reevaluate',json={'extra_features':{'recommendation_assessment':a}})
    assert r.status_code==422
    assert r.json()['detail']['code']=='JUDGMENT_COMMERCIAL_FIELD_FORBIDDEN'
