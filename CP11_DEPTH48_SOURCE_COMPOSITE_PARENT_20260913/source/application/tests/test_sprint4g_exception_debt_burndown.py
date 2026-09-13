import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4g_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,JourneyRecoveryExceptionDebtRow,JourneyRecoveryDebtBurnDownMilestoneRow
from go_hotel.journey.recovery_exception_debt_burndown import recovery_exception_debt_burndown_service as svc
from go_hotel.journey.recovery_continuous_chaos import recovery_continuous_chaos_service as waiver

def setup_function():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

def policy(**kw):
    p=dict(freeze_trigger_debt_points=100,release_threshold_debt_points=35,max_debt_age_seconds=3600,plan_due_seconds=7200,milestone_overdue_escalation_seconds=60,executive_acceptance_max_seconds=86400)
    p.update(kw)
    return svc.create_policy('prod-debt-burndown','PROD',p['freeze_trigger_debt_points'],p['release_threshold_debt_points'],p['max_debt_age_seconds'],p['plan_due_seconds'],p['milestone_overdue_escalation_seconds'],p['executive_acceptance_max_seconds'],'governance')

def debt(points=120,state='BLOCKED',age_seconds=10):
    with SessionLocal() as s:
        x=JourneyRecoveryExceptionDebtRow(exception_debt_id=f'debt-{points}-{age_seconds}',environment='PROD',waiver_exposure_policy_id='4f-policy',rolling_window_start=datetime.now(timezone.utc)-timedelta(hours=1),rolling_waiver_count=3,consecutive_waiver_releases=2,exposure_seconds=100,open_remediation_count=2,overdue_remediation_count=1,debt_points=points,debt_state=state,reason_codes_json=['TEST_DEBT'],evaluated_by='test',evaluated_at=datetime.now(timezone.utc)-timedelta(seconds=age_seconds),supplier_fact_unchanged=True)
        s.add(x);s.commit();return x.exception_debt_id

def plan(two=True):
    ms=[{'title':'Fix witness readiness','owner_team':'trust-platform','accountable_owner':'trust-lead','target_debt_reduction_points':40}]
    if two:ms.append({'title':'Close waiver remediation','owner_team':'release-engineering','accountable_owner':'release-lead','target_debt_reduction_points':40})
    return svc.create_plan('PROD','program-owner','exec-sponsor','Burn exception debt below release threshold',30,ms,[{'team_key':'trust-platform','responsible_owner':'trust-lead','accountable_executive':'exec-sponsor','consulted':['security'],'informed':['release']}],'planner')

def test_policy_versions_and_rejects_unsafe_thresholds():
    p1=policy();p2=policy(max_debt_age_seconds=7200)
    assert p1['version_no']==1 and p2['version_no']==2 and p2['state']=='ACTIVE'
    with pytest.raises(ValueError,match='INVALID_DEBT_BURN_DOWN_THRESHOLDS'):
        svc.create_policy('bad','PROD',50,50,1,1,1,1,'x')

def test_high_exception_debt_activates_freeze_and_blocks_legacy_waiver_request():
    policy();debt(140)
    a=svc.evaluate_aging('PROD','risk-bot')
    assert a['aging_state']=='CRITICAL' and 'DEBT_POINTS_FREEZE_THRESHOLD_EXCEEDED' in a['reason_codes']
    st=svc.status('PROD');assert st['freezes'][0]['state']=='ACTIVE'
    with pytest.raises(ValueError,match='ACTIVE_DEBT_FREEZE'):
        waiver.request_waiver('PROD','emergency','risk','evidence://w','risk-owner',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(hours=1),'requester')

def test_burndown_plan_requires_milestones_and_builds_cross_team_responsibility_matrix():
    policy();debt(120);svc.evaluate_aging('PROD')
    p=plan()
    assert p['starting_debt_points']==120 and p['target_debt_points']==30
    assert len(p['milestones'])==2 and p['responsibility_matrix'][0]['accountable_executive']=='exec-sponsor'
    with pytest.raises(ValueError,match='BURN_DOWN_MILESTONES_REQUIRED'):
        svc.create_plan('PROD','o','e','x',20,[],[],'x')

def test_milestone_completion_requires_evidence_and_updates_plan_progress():
    policy();debt(120);svc.evaluate_aging('PROD');p=plan()
    m1=p['milestones'][0]['debt_burn_down_milestone_id'];m2=p['milestones'][1]['debt_burn_down_milestone_id']
    with pytest.raises(ValueError,match='MILESTONE_EVIDENCE_REQUIRED'):svc.complete_milestone(m1,'','owner')
    svc.complete_milestone(m1,'fix://one','owner');assert svc.plan(p['debt_burn_down_plan_id'])['progress_percent']==50
    svc.complete_milestone(m2,'fix://two','owner');assert svc.plan(p['debt_burn_down_plan_id'])['progress_percent']==100

def test_overdue_burndown_milestone_escalates_automatically():
    policy(milestone_overdue_escalation_seconds=1);debt(120);svc.evaluate_aging('PROD');p=plan(two=False)
    mid=p['milestones'][0]['debt_burn_down_milestone_id']
    with SessionLocal() as s:
        m=s.get(JourneyRecoveryDebtBurnDownMilestoneRow,mid);m.due_at=datetime.now(timezone.utc)-timedelta(seconds=5);s.commit()
    out=svc.governance_tick('PROD','scheduler')
    assert mid in out['escalated'] and svc.plan(p['debt_burn_down_plan_id'])['milestones'][0]['state']=='ESCALATED'

def test_executive_risk_acceptance_requires_two_distinct_executives_and_time_bound_window():
    policy(executive_acceptance_max_seconds=3600);debt(120);svc.evaluate_aging('PROD');p=plan(two=False)
    a=svc.request_executive_acceptance(p['debt_burn_down_plan_id'],'Residual risk cannot be eliminated before market launch','risk://board',datetime.now(timezone.utc)-timedelta(seconds=1),datetime.now(timezone.utc)+timedelta(minutes=30),'requester')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_executive_acceptance(a['executive_risk_acceptance_id'],'requester')
    a=svc.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-a');assert a['state']=='AWAITING_SECOND_APPROVAL'
    with pytest.raises(ValueError,match='TWO_DISTINCT'):svc.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-a')
    a=svc.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-b');assert a['state']=='APPROVED'
    with pytest.raises(ValueError,match='INVALID_EXECUTIVE_RISK_ACCEPTANCE_WINDOW'):
        svc.request_executive_acceptance(p['debt_burn_down_plan_id'],'x','e://x',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(hours=2),'r2')

def test_freeze_releases_normally_only_after_debt_below_release_threshold():
    policy();debt(120);svc.evaluate_aging('PROD');p=plan(two=False)
    with pytest.raises(ValueError,match='RELEASE_CONDITIONS_NOT_MET'):svc.release_freeze('PROD','release://too-early','risk')
    debt(20,'HEALTHY',1)
    f=svc.release_freeze('PROD','release://debt-cleared','risk')
    assert f['state']=='RELEASED' and f['release_evidence_reference']=='release://debt-cleared'

def test_residual_risk_acceptance_does_not_bypass_freeze_and_only_supports_controlled_release_after_plan_complete():
    policy();debt(130);svc.evaluate_aging('PROD');p=plan(two=False)
    a=svc.request_executive_acceptance(p['debt_burn_down_plan_id'],'Residual risk remains after planned mitigations','risk://accepted',datetime.now(timezone.utc)-timedelta(seconds=1),datetime.now(timezone.utc)+timedelta(hours=1),'risk-requester')
    svc.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-a');svc.approve_executive_acceptance(a['executive_risk_acceptance_id'],'exec-b')
    with pytest.raises(ValueError,match='RELEASE_CONDITIONS_NOT_MET'):svc.release_freeze('PROD','release://before-plan','risk')
    mid=p['milestones'][0]['debt_burn_down_milestone_id'];svc.complete_milestone(mid,'fix://done','owner')
    f=svc.release_freeze('PROD','release://controlled-residual-risk','risk')
    assert f['state']=='RELEASED'
    # Executive acceptance is not the waiver, but while it is active and the plan is complete it prevents immediate re-freeze.
    a2=svc.pre_request_waiver('PROD','requester')
    assert a2['aging_state']=='ACCEPTED_RESIDUAL_RISK'
    st=svc.status('PROD');assert st['executive_acceptances'][0]['state']=='ACTIVE' and st['plans'][0]['progress_percent']==100
