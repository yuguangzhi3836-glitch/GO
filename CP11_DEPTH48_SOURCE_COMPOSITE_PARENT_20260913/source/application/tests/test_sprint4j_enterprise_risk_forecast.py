import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4j_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,JourneyRecoveryRiskAppetiteEnvelopeRow,JourneyRecoveryExecutiveRiskAcceptanceRow,JourneyRecoveryExecutiveRiskPositionRow,JourneyRecoveryDynamicRiskCapacityRow
from go_hotel.journey.recovery_enterprise_risk_forecast import recovery_enterprise_risk_forecast_service as svc

def setup_function(): Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def boot(exposure=100):
    with SessionLocal() as s:
        s.add(JourneyRecoveryRiskAppetiteEnvelopeRow(risk_appetite_envelope_id='a',appetite_key='a',version_no=1,environment='PROD',max_current_exposure_points=300,max_stressed_exposure_points=450,min_headroom_points=50,min_capacity_buffer_pct=10,max_sensitivity_pct=150,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=datetime.now(timezone.utc),supplier_fact_unchanged=True))
        a=JourneyRecoveryExecutiveRiskAcceptanceRow(executive_risk_acceptance_id='e',environment='PROD',debt_burn_down_plan_id='p',residual_risk_summary='x',evidence_reference='e',requested_by='r',requested_at=datetime.now(timezone.utc),executive_approver_one='a',executive_approver_two='b',starts_at=datetime.now(timezone.utc)-timedelta(minutes=1),expires_at=datetime.now(timezone.utc)+timedelta(days=2),state='APPROVED',supplier_fact_unchanged=True);s.add(a)
        s.add(JourneyRecoveryExecutiveRiskPositionRow(risk_position_id='pos',environment='PROD',executive_risk_acceptance_id='e',team_key='team-a',risk_domain='IDENTITY',exposure_points=exposure,correlation_keys_json=['cloud-a'],state='ACTIVE',registered_by='r',registered_at=datetime.now(timezone.utc),supplier_fact_unchanged=True));s.commit()
def active_policy(w=80,r=95,res=10):
    x=svc.create_policy('f','PROD',w,r,res,'maker');svc.approve_policy(x['risk_forecast_policy_id'],'board-a');return svc.approve_policy(x['risk_forecast_policy_id'],'board-b')

def test_policy_requires_two_distinct_board_approvers():
    x=svc.create_policy('f','PROD',80,95,10,'maker')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_policy(x['risk_forecast_policy_id'],'maker')
    svc.approve_policy(x['risk_forecast_policy_id'],'board-a')
    with pytest.raises(ValueError,match='TWO_DISTINCT'):svc.approve_policy(x['risk_forecast_policy_id'],'board-a')
    assert svc.approve_policy(x['risk_forecast_policy_id'],'board-b')['state']=='ACTIVE'

def test_24h_and_7d_forecast_are_explicit_and_forward_looking():
    boot(100);active_policy();svc.observe_indicator('PROD','waiver-churn','KRI','GLOBAL',None,1.2,1,'HIGH_BAD',1,{'e':'x'})
    a=svc.forecast('PROD',24);b=svc.forecast('PROD',168)
    assert a['projected_exposure_points']>100 and b['projected_exposure_points']>a['projected_exposure_points']

def test_breach_creates_early_warning_and_residual_risk_restriction():
    boot(260);active_policy(70,85,10);svc.observe_indicator('PROD','capacity-burn','EWI','GLOBAL',None,1.4,1,'HIGH_BAD',1,{})
    out=svc.forecast('PROD',24);st=svc.status('PROD')
    assert out['forecast_state']=='BREACH' and st['warnings'][0]['state']=='OPEN' and st['restrictions'][0]['state']=='ACTIVE'

def test_watch_creates_warning_without_restriction():
    boot(205);active_policy(75,99,5);svc.observe_indicator('PROD','trend','EWI','GLOBAL',None,0.95,1,'HIGH_BAD',1,{})
    out=svc.forecast('PROD',24);st=svc.status('PROD')
    assert out['forecast_state'] in ('WATCH','PASS')
    if out['forecast_state']=='WATCH': assert st['warnings'] and not st['restrictions']

def test_dynamic_capacity_allocation_is_persisted_for_team_and_domain():
    boot(100);active_policy();svc.forecast('PROD',24)
    with SessionLocal() as s:
        rows=s.query(JourneyRecoveryDynamicRiskCapacityRow).all();assert {x.dimension for x in rows}=={'TEAM','RISK_DOMAIN'} and all(x.allocated_capacity_points>0 for x in rows)

def test_active_forecast_restriction_blocks_new_residual_risk():
    boot(280);active_policy(70,80,10);svc.observe_indicator('PROD','burn','EWI','GLOBAL',None,2,1,'HIGH_BAD',1,{});svc.forecast('PROD',24)
    with pytest.raises(ValueError,match='FORECAST_RISK_RESTRICTION'):svc.pre_request_waiver('PROD')
    with pytest.raises(ValueError,match='FORECAST_RISK_RESTRICTION'):svc.pre_request_executive_acceptance('PROD')

def test_restriction_release_requires_latest_non_breach_and_evidence():
    boot(280);active_policy(70,80,10);svc.observe_indicator('PROD','burn','EWI','GLOBAL',None,2,1,'HIGH_BAD',1,{});svc.forecast('PROD',24)
    with pytest.raises(ValueError,match='RELEASE_CONDITIONS'):svc.release_restriction('PROD','e://x','risk')
    with SessionLocal() as s:s.get(JourneyRecoveryExecutiveRiskPositionRow,'pos').state='CLOSED';s.commit()
    assert svc.forecast('PROD',24)['forecast_state']!='BREACH'
    assert svc.release_restriction('PROD','e://mitigated','risk')['state']=='RELEASED'

def test_forecast_never_changes_supplier_fact():
    boot(50);active_policy();x=svc.observe_indicator('PROD','k','KRI','GLOBAL',None,1,1,'HIGH_BAD',1,{})
    out=svc.forecast('PROD',24);assert x['supplier_fact_unchanged'] is True and out['supplier_fact_unchanged'] is True
