import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4e_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,JourneyRecoveryChaosScheduleRow,JourneyRecoveryReadinessAssessmentRow,JourneyRecoveryProductionReadinessGateRow,JourneyRecoveryProductionReleaseWaiverRow,JourneyRecoveryReleaseGateHistoryRow
from go_hotel.journey.recovery_trust_plane_chaos import recovery_trust_plane_chaos_service as chaos
from go_hotel.journey.recovery_continuous_chaos import recovery_continuous_chaos_service as svc

SCENARIOS=[{'scenario_type':x,'fault_parameters':{}} for x in ['WITNESS_LOSS','REGION_LOSS','PROVIDER_LOSS','STALE_CHECKPOINT','ARCHIVE_CORRUPTION','QUORUM_DEGRADATION']]

def setup_function():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

def policy(ttl=3600):
    return chaos.create_policy('prod-readiness','PROD',[x['scenario_type'] for x in SCENARIOS],90,300,60,ttl,'maker')

def full_pass(actor='ops'):
    policy();c=chaos.create_campaign('PROD','manual',SCENARIOS,actor);chaos.run_campaign(c['chaos_campaign_id'],actor);a=chaos.assess_readiness(c['chaos_campaign_id'],actor);g=chaos.evaluate_gate(a['readiness_assessment_id'],'gate://ok',actor);return c,a,g

def test_scheduler_runs_due_campaign_and_advances_next_run():
    policy();sch=svc.create_schedule('PROD','nightly',3600,SCENARIOS,'ops')
    out=svc.tick('PROD','scheduler')
    assert len(out['ran'])==1
    with SessionLocal() as s:
        x=s.get(JourneyRecoveryChaosScheduleRow,sch['chaos_schedule_id'])
        assert x.last_run_at is not None and x.next_run_at>x.last_run_at
    assert svc.tick('PROD','scheduler')['ran']==[]

def test_readiness_trend_detects_rto_regression():
    policy()
    c1=chaos.create_campaign('PROD','c1',[{'scenario_type':'REGION_LOSS','fault_parameters':{'rto_seconds':10}}],'ops');chaos.run_campaign(c1['chaos_campaign_id'],'ops');chaos.assess_readiness(c1['chaos_campaign_id'],'ops')
    c2=chaos.create_campaign('PROD','c2',[{'scenario_type':'REGION_LOSS','fault_parameters':{'rto_seconds':80}}],'ops');chaos.run_campaign(c2['chaos_campaign_id'],'ops');chaos.assess_readiness(c2['chaos_campaign_id'],'ops')
    t=svc.evaluate_trend('PROD','ops')
    assert t['trend_state']=='REGRESSED' and 'RTO_REGRESSION' in t['reason_codes']

def test_evidence_aging_marks_trend_regressed():
    policy(ttl=5);c=chaos.create_campaign('PROD','old',SCENARIOS,'ops');chaos.run_campaign(c['chaos_campaign_id'],'ops');a=chaos.assess_readiness(c['chaos_campaign_id'],'ops')
    with SessionLocal() as s:
        x=s.get(JourneyRecoveryReadinessAssessmentRow,a['readiness_assessment_id']);x.assessed_at=datetime.now(timezone.utc)-timedelta(seconds=30);s.commit()
    t=svc.evaluate_trend('PROD','ops')
    assert 'READINESS_EVIDENCE_AGED_OUT' in t['reason_codes']

def test_waiver_requires_two_distinct_approvers_and_requester_cannot_approve():
    policy();w=svc.request_waiver('PROD','urgent fix','accept stale readiness','waiver://1','risk-owner',datetime.now(timezone.utc)-timedelta(seconds=1),datetime.now(timezone.utc)+timedelta(hours=1),'requester')
    with pytest.raises(ValueError,match='WAIVER_MAKER_CHECKER_REQUIRED'):svc.approve_waiver(w['production_release_waiver_id'],'requester')
    w=svc.approve_waiver(w['production_release_waiver_id'],'approver-a');assert w['state']=='AWAITING_SECOND_APPROVAL'
    with pytest.raises(ValueError,match='TWO_DISTINCT'):svc.approve_waiver(w['production_release_waiver_id'],'approver-a')
    w=svc.approve_waiver(w['production_release_waiver_id'],'approver-b');assert w['state']=='APPROVED'
    assert svc.active_waiver('PROD')['risk_acceptor']=='risk-owner'

def test_waiver_auto_expires_and_cannot_authorize_release():
    policy();w=svc.request_waiver('PROD','urgent','risk','waiver://2','risk-owner',datetime.now(timezone.utc)-timedelta(minutes=2),datetime.now(timezone.utc)+timedelta(minutes=1),'requester');svc.approve_waiver(w['production_release_waiver_id'],'a');svc.approve_waiver(w['production_release_waiver_id'],'b')
    with SessionLocal() as s:
        x=s.get(JourneyRecoveryProductionReleaseWaiverRow,w['production_release_waiver_id']);x.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
    assert svc.active_waiver('PROD') is None
    out=svc.authorize_release('PROD','manifest-x','deployer');assert out['allowed'] is False

def test_valid_gate_authorizes_without_waiver_and_records_history():
    _,_,g=full_pass();out=svc.authorize_release('PROD','manifest-ok','deployer')
    assert out['allowed'] is True and out['reason']=='READINESS_GATE_PASS' and out['waiver'] is None
    with SessionLocal() as s:
        h=s.execute(select(JourneyRecoveryReleaseGateHistoryRow)).scalars().one();assert h.gate_id==g['production_readiness_gate_id'] and h.waiver_id is None

def test_blocked_gate_can_only_be_bypassed_by_active_approved_waiver():
    policy();assert svc.authorize_release('PROD','m0','deployer')['allowed'] is False
    w=svc.request_waiver('PROD','emergency','known risk','waiver://3','vp-risk',datetime.now(timezone.utc)-timedelta(seconds=1),datetime.now(timezone.utc)+timedelta(hours=1),'requester');svc.approve_waiver(w['production_release_waiver_id'],'a');svc.approve_waiver(w['production_release_waiver_id'],'b')
    out=svc.authorize_release('PROD','m1','deployer');assert out['allowed'] is True and out['reason']=='APPROVED_TIME_BOUND_WAIVER'
    with SessionLocal() as s:
        hs=s.execute(select(JourneyRecoveryReleaseGateHistoryRow).order_by(JourneyRecoveryReleaseGateHistoryRow.evaluated_at)).scalars().all();assert hs[-1].waiver_id==w['production_release_waiver_id']

def test_waiver_window_is_hard_bounded_and_supplier_fact_unchanged():
    policy()
    with pytest.raises(ValueError,match='WAIVER_MAX_DURATION_24_HOURS'):
        svc.request_waiver('PROD','x','y','waiver://4','risk',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(hours=25),'requester')
    w=svc.request_waiver('PROD','x','y','waiver://5','risk',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(hours=1),'requester')
    assert w['supplier_fact_unchanged'] is True
