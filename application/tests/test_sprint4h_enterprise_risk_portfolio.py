import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4h_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,JourneyRecoveryExceptionDebtRow,JourneyRecoveryExecutiveRiskPositionRow
from go_hotel.journey.recovery_exception_debt_burndown import recovery_exception_debt_burndown_service as debt
from go_hotel.journey.recovery_enterprise_risk_portfolio import recovery_enterprise_risk_portfolio_service as svc
from go_hotel.journey.recovery_continuous_chaos import recovery_continuous_chaos_service as waiver

def setup_function(): Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def debt_policy(): return debt.create_policy('4h-debt','PROD',100,35,3600,7200,60,86400,'gov')
def add_debt(points=130):
    with SessionLocal() as s:
        x=JourneyRecoveryExceptionDebtRow(exception_debt_id=f'debt-{points}',environment='PROD',waiver_exposure_policy_id='4f',rolling_window_start=datetime.now(timezone.utc)-timedelta(hours=1),rolling_waiver_count=2,consecutive_waiver_releases=1,exposure_seconds=100,open_remediation_count=1,overdue_remediation_count=0,debt_points=points,debt_state='BLOCKED',reason_codes_json=['T'],evaluated_by='t',evaluated_at=datetime.now(timezone.utc),supplier_fact_unchanged=True);s.add(x);s.commit()
def make_acceptance(summary='risk'):
    p=debt.create_plan('PROD','owner','sponsor','fix',30,[{'title':'done','owner_team':'team-a','accountable_owner':'lead','target_debt_reduction_points':90}],[],'planner')
    mid=p['milestones'][0]['debt_burn_down_milestone_id'];debt.complete_milestone(mid,'e://done','lead')
    a=debt.request_executive_acceptance(p['debt_burn_down_plan_id'],summary,'risk://e',datetime.now(timezone.utc)-timedelta(seconds=1),datetime.now(timezone.utc)+timedelta(hours=1),'requester')
    debt.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-a');return debt.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-b')
def active_limit(**kw):
    d=dict(max_aggregate_exposure_points=300,max_team_concentration_pct=80,max_risk_domain_concentration_pct=80,max_correlated_exposure_points=250,max_active_acceptances=6);d.update(kw)
    x=svc.create_limit('board-limit','PROD',d['max_aggregate_exposure_points'],d['max_team_concentration_pct'],d['max_risk_domain_concentration_pct'],d['max_correlated_exposure_points'],d['max_active_acceptances'],'maker')
    svc.approve_limit(x['enterprise_risk_limit_id'],'board-a');return svc.approve_limit(x['enterprise_risk_limit_id'],'board-b')

def test_board_risk_limit_requires_two_distinct_approvers():
    x=svc.create_limit('l','PROD',100,80,80,80,3,'maker')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_limit(x['enterprise_risk_limit_id'],'maker')
    svc.approve_limit(x['enterprise_risk_limit_id'],'board-a')
    with pytest.raises(ValueError,match='TWO_DISTINCT'):svc.approve_limit(x['enterprise_risk_limit_id'],'board-a')
    x=svc.approve_limit(x['enterprise_risk_limit_id'],'board-b');assert x['state']=='ACTIVE'

def test_position_requires_approved_acceptance_and_explicit_dimensions():
    debt_policy();add_debt();a=make_acceptance();active_limit()
    p=svc.register_position(a['executive_risk_acceptance_id'],'trust-platform','IDENTITY',40,['provider-a'],'risk-office')
    assert p['team_key']=='trust-platform' and p['risk_domain']=='IDENTITY' and p['exposure_points']==40
    with pytest.raises(ValueError,match='ALREADY_REGISTERED'):svc.register_position(a['executive_risk_acceptance_id'],'x','y',1,[],'r')

def test_aggregate_exposure_breach_activates_portfolio_freeze():
    debt_policy();add_debt();active_limit(max_aggregate_exposure_points=50)
    a=make_acceptance();svc.register_position(a['executive_risk_acceptance_id'],'team-a','IDENTITY',60,['shared-cloud'],'r')
    x=svc.evaluate('PROD','risk-engine');assert x['portfolio_state']=='BREACH' and 'AGGREGATE_EXPOSURE_LIMIT_EXCEEDED' in x['reason_codes']
    assert svc.status('PROD')['freezes'][0]['state']=='ACTIVE'

def test_team_domain_and_correlation_concentration_are_explicit():
    debt_policy();add_debt();active_limit(max_team_concentration_pct=55,max_risk_domain_concentration_pct=55,max_correlated_exposure_points=70)
    a1=make_acceptance('r1');svc.register_position(a1['executive_risk_acceptance_id'],'team-a','IDENTITY',60,['shared'],'r')
    a2=make_acceptance('r2');svc.register_position(a2['executive_risk_acceptance_id'],'team-a','IDENTITY',40,['shared'],'r')
    x=svc.evaluate('PROD');assert x['portfolio_state']=='BREACH'
    assert {'TEAM_CONCENTRATION_LIMIT_EXCEEDED','RISK_DOMAIN_CONCENTRATION_LIMIT_EXCEEDED','CORRELATED_EXPOSURE_LIMIT_EXCEEDED'} <= set(x['reason_codes'])

def test_portfolio_freeze_blocks_new_waiver_and_new_executive_acceptance():
    debt_policy();add_debt();active_limit(max_aggregate_exposure_points=50)
    a=make_acceptance();svc.register_position(a['executive_risk_acceptance_id'],'team-a','IDENTITY',60,[],'r');svc.evaluate('PROD')
    with pytest.raises(ValueError,match='PORTFOLIO_FREEZE'):debt.request_executive_acceptance(debt.status('PROD')['plans'][0]['debt_burn_down_plan_id'],'new','e://x',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=30),'new-maker')
    with pytest.raises(ValueError,match='PORTFOLIO_FREEZE'):waiver.request_waiver('PROD','x','x','e://w','risk-owner',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=30),'maker')

def test_4g_residual_risk_release_requires_registered_portfolio_position_when_limit_active():
    debt_policy();add_debt();debt.evaluate_aging('PROD');active_limit();a=make_acceptance()
    with pytest.raises(ValueError,match='POSITION_REGISTRATION_REQUIRED'):debt.release_freeze('PROD','release://x','risk')
    svc.register_position(a['executive_risk_acceptance_id'],'team-a','IDENTITY',40,[],'r');f=debt.release_freeze('PROD','release://ok','risk');assert f['state']=='RELEASED'

def test_freeze_release_requires_portfolio_back_within_board_limit():
    debt_policy();add_debt();active_limit(max_aggregate_exposure_points=50)
    a=make_acceptance();p=svc.register_position(a['executive_risk_acceptance_id'],'team-a','IDENTITY',60,[],'r');svc.evaluate('PROD')
    with pytest.raises(ValueError,match='RELEASE_CONDITIONS_NOT_MET'):svc.release_freeze('PROD','e://x','board-risk')
    with SessionLocal() as s:
        row=s.get(JourneyRecoveryExecutiveRiskPositionRow,p['risk_position_id']);row.state='CLOSED';s.commit()
    f=svc.release_freeze('PROD','e://mitigated','board-risk');assert f['state']=='RELEASED'

def test_expired_acceptance_drops_out_of_effective_portfolio_exposure():
    debt_policy();add_debt();active_limit(max_aggregate_exposure_points=50)
    a=make_acceptance();svc.register_position(a['executive_risk_acceptance_id'],'team-a','IDENTITY',40,[],'r')
    assert svc.evaluate('PROD')['aggregate_exposure_points']==40
    from go_hotel.db.models import JourneyRecoveryExecutiveRiskAcceptanceRow
    with SessionLocal() as s:
        x=s.get(JourneyRecoveryExecutiveRiskAcceptanceRow,a['executive_risk_acceptance_id']);x.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
    out=svc.evaluate('PROD');assert out['aggregate_exposure_points']==0 and out['portfolio_state']=='PASS'
