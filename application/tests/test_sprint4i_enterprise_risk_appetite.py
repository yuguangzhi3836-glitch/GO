import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4i_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,JourneyRecoveryExceptionDebtRow,JourneyRecoveryExecutiveRiskPositionRow
from go_hotel.journey.recovery_exception_debt_burndown import recovery_exception_debt_burndown_service as debt
from go_hotel.journey.recovery_enterprise_risk_portfolio import recovery_enterprise_risk_portfolio_service as portfolio
from go_hotel.journey.recovery_enterprise_risk_appetite import recovery_enterprise_risk_appetite_service as svc
from go_hotel.journey.recovery_continuous_chaos import recovery_continuous_chaos_service as waiver

def setup_function(): Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def bootstrap_debt():
    debt.create_policy('4i-debt','PROD',100,35,3600,7200,60,86400,'gov')
    with SessionLocal() as s:
        s.add(JourneyRecoveryExceptionDebtRow(exception_debt_id='d',environment='PROD',waiver_exposure_policy_id='4f',rolling_window_start=datetime.now(timezone.utc)-timedelta(hours=1),rolling_waiver_count=1,consecutive_waiver_releases=1,exposure_seconds=100,open_remediation_count=1,overdue_remediation_count=0,debt_points=130,debt_state='BLOCKED',reason_codes_json=['T'],evaluated_by='t',evaluated_at=datetime.now(timezone.utc),supplier_fact_unchanged=True));s.commit()
def make_acceptance(name='risk'):
    p=debt.create_plan('PROD','owner','sponsor','fix',30,[{'title':'done','owner_team':'team-a','accountable_owner':'lead','target_debt_reduction_points':100}],[],'planner')
    debt.complete_milestone(p['milestones'][0]['debt_burn_down_milestone_id'],'e://done','lead')
    a=debt.request_executive_acceptance(p['debt_burn_down_plan_id'],name,'risk://e',datetime.now(timezone.utc)-timedelta(seconds=1),datetime.now(timezone.utc)+timedelta(hours=1),'requester')
    debt.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-a');return debt.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-b')
def active_limit(max_agg=500):
    x=portfolio.create_limit('l','PROD',max_agg,90,90,450,10,'maker');portfolio.approve_limit(x['enterprise_risk_limit_id'],'board-a');return portfolio.approve_limit(x['enterprise_risk_limit_id'],'board-b')
def active_appetite(max_current=400,max_stressed=500,min_headroom=80,min_buffer=15,max_sens=150):
    x=svc.create_appetite('a','PROD',max_current,max_stressed,min_headroom,min_buffer,max_sens,'maker');svc.approve_appetite(x['risk_appetite_envelope_id'],'board-a');return svc.approve_appetite(x['risk_appetite_envelope_id'],'board-b')
def add_position(points=100,corr=None,domain='IDENTITY'):
    a=make_acceptance();return portfolio.register_position(a['executive_risk_acceptance_id'],'team-a',domain,points,corr or ['cloud-a'],'r')

def test_risk_appetite_requires_two_distinct_board_approvers():
    x=svc.create_appetite('a','PROD',100,150,20,10,100,'maker')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_appetite(x['risk_appetite_envelope_id'],'maker')
    svc.approve_appetite(x['risk_appetite_envelope_id'],'board-a')
    with pytest.raises(ValueError,match='TWO_DISTINCT'):svc.approve_appetite(x['risk_appetite_envelope_id'],'board-a')
    assert svc.approve_appetite(x['risk_appetite_envelope_id'],'board-b')['state']=='ACTIVE'

def test_current_portfolio_can_pass_while_stress_breaches_appetite_and_freezes():
    bootstrap_debt();active_limit(500);active_appetite(max_stressed=220,min_headroom=40,min_buffer=10,max_sens=200);add_position(100)
    assert portfolio.evaluate('PROD')['portfolio_state']=='PASS'
    sc=svc.create_scenario('PROD','cloud-a-down','CLOUD_PROVIDER',2.5,1,['cloud-a'],[],'risk')
    out=svc.evaluate('PROD',[sc['stress_scenario_id']]);assert out['assessment_state']=='BREACH' and out['stressed_exposure_points']==250
    assert svc.status('PROD')['stress_freezes'][0]['state']=='ACTIVE'

def test_headroom_buffer_and_sensitivity_are_explicit():
    bootstrap_debt();active_limit();active_appetite(max_stressed=400,min_headroom=120,min_buffer=30,max_sens=40);add_position(100)
    sc=svc.create_scenario('PROD','identity-root-shock','IDENTITY_ROOT',1.5,1,[],['IDENTITY'],'risk')
    out=svc.evaluate('PROD',[sc['stress_scenario_id']]);assert out['headroom_points']==250 and out['capacity_buffer_pct']==62.5 and out['sensitivity_pct']==50
    assert 'PORTFOLIO_SENSITIVITY_LIMIT_EXCEEDED' in out['reason_codes']

def test_correlation_amplifier_increases_stressed_exposure():
    bootstrap_debt();active_limit();active_appetite(max_stressed=1000,min_headroom=10,min_buffer=1,max_sens=500);add_position(100,['shared-provider'])
    sc=svc.create_scenario('PROD','correlated','COMBINED',1.5,2,['shared-provider'],[],'risk')
    assert svc.evaluate('PROD',[sc['stress_scenario_id']])['stressed_exposure_points']==300

def test_stress_freeze_blocks_new_waiver_and_new_executive_acceptance():
    bootstrap_debt();active_limit();active_appetite(max_stressed=150,min_headroom=20,min_buffer=10,max_sens=300);add_position(100)
    sc=svc.create_scenario('PROD','region-loss','REGION',2,1,[],[],'risk');svc.evaluate('PROD',[sc['stress_scenario_id']])
    with pytest.raises(ValueError,match='STRESS_PREEMPTIVE_FREEZE'):waiver.request_waiver('PROD','x','x','e://w','risk-owner',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=20),'maker')
    plan=debt.status('PROD')['plans'][0]
    with pytest.raises(ValueError,match='STRESS_PREEMPTIVE_FREEZE'):debt.request_executive_acceptance(plan['debt_burn_down_plan_id'],'x','e://x',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=20),'maker2')

def test_4g_residual_risk_release_is_blocked_by_active_stress_freeze():
    bootstrap_debt();debt.evaluate_aging('PROD');active_limit();active_appetite(max_stressed=150,min_headroom=20,min_buffer=10,max_sens=300);p=add_position(100)
    sc=svc.create_scenario('PROD','root','IDENTITY_ROOT',2,1,[],[],'risk');svc.evaluate('PROD',[sc['stress_scenario_id']])
    with pytest.raises(ValueError,match='STRESS_PREEMPTIVE_FREEZE'):debt.release_freeze('PROD','release://x','risk')

def test_freeze_release_requires_latest_non_breach_stress_assessment_and_evidence():
    bootstrap_debt();active_limit();a=active_appetite(max_stressed=150,min_headroom=20,min_buffer=10,max_sens=300);p=add_position(100)
    bad=svc.create_scenario('PROD','bad','REGION',2,1,[],[],'risk');svc.evaluate('PROD',[bad['stress_scenario_id']])
    with pytest.raises(ValueError,match='RELEASE_CONDITIONS'):svc.release_freeze('PROD','e://x','board-risk')
    with SessionLocal() as s:
        row=s.get(JourneyRecoveryExecutiveRiskPositionRow,p['risk_position_id']);row.state='CLOSED';s.commit()
    good=svc.create_scenario('PROD','good','REGION',1,1,[],[],'risk');assert svc.evaluate('PROD',[good['stress_scenario_id']])['assessment_state']!='BREACH'
    assert svc.release_freeze('PROD','e://mitigated','board-risk')['state']=='RELEASED'

def test_stress_assessment_never_changes_supplier_fact():
    bootstrap_debt();active_limit();active_appetite();add_position(50)
    sc=svc.create_scenario('PROD','release-control','RELEASE_CONTROL',1.2,1,[],[],'risk');out=svc.evaluate('PROD',[sc['stress_scenario_id']])
    assert out['supplier_fact_unchanged'] is True
