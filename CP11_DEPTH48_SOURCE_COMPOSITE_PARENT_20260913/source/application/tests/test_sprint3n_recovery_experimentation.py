from go_hotel.db.session import SessionLocal
from go_hotel.journey.recovery_strategy_governance import recovery_strategy_governance_service as gov
from go_hotel.journey.recovery_experimentation import recovery_experimentation_service as exp
from go_hotel.security.service import identity_service
from go_hotel.db.models import JourneyRecoveryStrategyVersionRow

def ah():
    t=identity_service.login('go_admin','change-me-admin');return {'Authorization':'Bearer '+t['access_token']}

def strategies():
    with SessionLocal() as s:gov.bootstrap(s);s.commit()
    c=gov.create('3n-candidate',5,0.0,20);gov.approve(c,'admin');gov.activate(c,'CANARY','admin');return 'recovery_guardrail_v1',c

def seed(eid,c_ok=20,c_n=20,k_ok=20,k_n=20,k_timeout=0,k_manual=0,vertical='RIDE',adapter='mobility_ride_recovery_v1'):
    for i in range(c_n):exp.observe(eid,f'c{i}','CONTROL',vertical,adapter,confirmed=i<c_ok,timeout=False,manual_review=False,confirmation_seconds=60)
    for i in range(k_n):exp.observe(eid,f'k{i}','CANDIDATE',vertical,adapter,confirmed=i<k_ok,timeout=i<k_timeout,manual_review=i<k_manual,confirmation_seconds=45)

def test_experiment_requires_approval_and_candidate_approval():
    control,cand=strategies();eid=exp.create('approval',control,cand,min_sample_per_arm=5)
    try:exp.start(eid,'admin');assert False
    except ValueError as e:assert 'EXPERIMENT_APPROVAL_REQUIRED' in str(e)
    exp.approve(eid,'admin');assert exp.start(eid,'admin')==eid

def test_deterministic_assignment_and_min_sample_gate():
    control,cand=strategies();eid=exp.create('small',control,cand,allocation_percent=20,min_sample_per_arm=10);exp.approve(eid,'admin');exp.start(eid,'admin')
    assert exp.assign(eid,'item-1')==exp.assign(eid,'item-1')
    seed(eid,c_ok=3,c_n=3,k_ok=3,k_n=3)
    r=exp.evaluate(eid);assert r['decision']=='CONTINUE' and 'MIN_SAMPLE_PER_ARM_NOT_MET' in r['reasons'] and r['supplier_fact_unchanged'] is True

def test_promotion_requires_significance_and_strata_coverage():
    control,cand=strategies();eid=exp.create('promote',control,cand,min_sample_per_arm=20,promotion_gate={'require_significance':True,'require_strata_coverage':True,'min_confirmation_lift':0.05});exp.approve(eid,'admin');exp.start(eid,'admin')
    seed(eid,c_ok=10,c_n=20,k_ok=20,k_n=20)
    r=exp.evaluate(eid);assert r['decision']=='PROMOTE' and r['p_value']<0.05
    with SessionLocal() as s:assert s.get(JourneyRecoveryStrategyVersionRow,cand).state=='ACTIVE'

def test_safety_guardrail_auto_degrades_candidate():
    control,cand=strategies();eid=exp.create('degrade',control,cand,min_sample_per_arm=20,promotion_gate={'require_significance':False,'require_strata_coverage':True,'max_timeout_delta':0.05,'max_manual_review_delta':0.05});exp.approve(eid,'admin');exp.start(eid,'admin')
    seed(eid,c_ok=18,c_n=20,k_ok=19,k_n=20,k_timeout=8,k_manual=7)
    r=exp.evaluate(eid);assert r['decision']=='DEGRADE' and 'SAFETY_GUARDRAIL_BREACH' in r['reasons']
    with SessionLocal() as s:assert s.get(JourneyRecoveryStrategyVersionRow,cand).state=='ROLLED_BACK'

def test_admin_api_and_calibration_pipeline(client):
    H=ah();control,cand=strategies();body={'name':'api-exp','control_strategy_version_id':control,'candidate_strategy_version_id':cand,'allocation_percent':20,'min_sample_per_arm':5,'significance_alpha':0.05,'promotion_gate':{'require_significance':False,'require_strata_coverage':True}}
    r=client.post('/internal/v1/recovery/experimentation/experiments',headers=H,json=body);assert r.status_code==200;eid=r.json()['data']['experiment_id']
    assert client.post(f'/internal/v1/recovery/experimentation/experiments/{eid}/approve',headers=H).status_code==200
    assert client.post(f'/internal/v1/recovery/experimentation/experiments/{eid}/start',headers=H).status_code==200
    seed(eid,c_ok=3,c_n=5,k_ok=5,k_n=5)
    er=client.post(f'/internal/v1/recovery/experimentation/experiments/{eid}/evaluate',headers=H);assert er.status_code==200 and er.json()['data']['decision']=='PROMOTE'
    cr=client.post(f'/internal/v1/recovery/experimentation/experiments/{eid}/calibrate',headers=H);assert cr.status_code==200 and cr.json()['data']['items'][0]['state']=='CALIBRATED'
    assert client.get('/internal/v1/recovery/experimentation/decisions',headers=H).status_code==200
    assert client.get('/internal/v1/recovery/experimentation/calibrations',headers=H).status_code==200
    paths=client.app.openapi()['paths'];assert not any('supplier-fact' in p and 'override' in p for p in paths)
