from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryReliabilityProfileRow,JourneyRecoveryStrategyEvaluationRow,JourneyRecoverySupplierOperationRow
from go_hotel.journey.recovery_strategy_governance import recovery_strategy_governance_service as svc
from go_hotel.journey.recovery_reliability import recovery_reliability_service
from go_hotel.security.service import identity_service
from test_sprint3j_recovery_evidence_control import unknown_ride

def ah():
 t=identity_service.login('go_admin','change-me-admin');return {'Authorization':'Bearer '+t['access_token']}

def test_min_sample_and_confidence_force_baseline(client):
 h,j,e,ride=unknown_ride(client,'3m-small@example.com');recovery_reliability_service.rebuild()
 with SessionLocal.begin() as s:
  p=s.execute(select(JourneyRecoveryReliabilityProfileRow).where(JourneyRecoveryReliabilityProfileRow.vertical=='RIDE')).scalars().first();g=svc.evaluate(s,p,ride['execution_item_id'])
  assert g['eligible'] is False and 'MIN_SAMPLE_NOT_MET' in g['reasons'] and g['applied']['max_attempts']==8

def test_shadow_canary_require_approval_and_do_not_mutate_supplier_fact(client):
 h,j,e,ride=unknown_ride(client,'3m-shadow@example.com');sid=svc.create('candidate',1,0,100)
 try: svc.activate(sid,'SHADOW','admin');assert False
 except ValueError as x: assert 'APPROVAL_REQUIRED' in str(x)
 svc.approve(sid,'admin');svc.activate(sid,'SHADOW','admin');recovery_reliability_service.rebuild()
 with SessionLocal.begin() as s:
  p=s.execute(select(JourneyRecoveryReliabilityProfileRow).where(JourneyRecoveryReliabilityProfileRow.vertical=='RIDE')).scalars().first();g=svc.evaluate(s,p,ride['execution_item_id']);assert g['mode']=='SHADOW' and g['applied']['max_attempts']==8
 with SessionLocal() as s:
  op=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_item_id==ride['execution_item_id'])).scalars().one();assert op.status=='UNKNOWN'

def test_bounds_and_confidence_intervals_are_recorded(client):
 h,j,e,ride=unknown_ride(client,'3m-bounds@example.com');recovery_reliability_service.rebuild()
 with SessionLocal.begin() as s:
  p=s.execute(select(JourneyRecoveryReliabilityProfileRow).where(JourneyRecoveryReliabilityProfileRow.vertical=='RIDE')).scalars().first();p.sample_count=100;p.confidence=1.0;p.recommended_max_attempts=999
  g=svc.evaluate(s,p,ride['execution_item_id']);assert 'timeout_rate' in g['confidence_intervals'];assert g['applied']['max_attempts']<=15

def test_admin_strategy_lifecycle_and_no_supplier_fact_override(client):
 H=ah();r=client.post('/internal/v1/recovery/strategy-governance/strategies',headers=H,json={'name':'ops-canary','min_sample_count':20,'min_confidence':.8,'rollout_percent':10});assert r.status_code==200;sid=r.json()['data']['strategy_version_id']
 assert client.post(f'/internal/v1/recovery/strategy-governance/strategies/{sid}/approve',headers=H).status_code==200
 assert client.post(f'/internal/v1/recovery/strategy-governance/strategies/{sid}/activate',headers=H,json={'mode':'CANARY'}).status_code==200
 assert client.get('/internal/v1/recovery/strategy-governance/strategies',headers=H).status_code==200
 assert client.post(f'/internal/v1/recovery/strategy-governance/strategies/{sid}/rollback',headers=H,json={'reason':'test rollback'}).status_code==200
 paths=client.app.openapi()['paths'];assert not any('override-supplier-fact' in p for p in paths)

def test_guardrail_tick_is_safe_without_active_candidate(client):
 H=ah();r=client.post('/internal/v1/recovery/strategy-governance/guardrail/tick',headers=H);assert r.status_code==200 and 'rolled_back' in r.json()['data']
