import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4f_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,JourneyRecoveryProductionReleaseWaiverRow,JourneyRecoveryWaiverRemediationRow,JourneyRecoveryWaiverExposureEventRow
from go_hotel.journey.recovery_trust_plane_chaos import recovery_trust_plane_chaos_service as chaos
from go_hotel.journey.recovery_continuous_chaos import recovery_continuous_chaos_service as waiver
from go_hotel.journey.recovery_waiver_exposure_governance import recovery_waiver_exposure_governance_service as svc

SCENARIOS=[{'scenario_type':x,'fault_parameters':{}} for x in ['WITNESS_LOSS','REGION_LOSS','PROVIDER_LOSS','STALE_CHECKPOINT','ARCHIVE_CORRUPTION','QUORUM_DEGRADATION']]

def setup_function():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

def readiness_policy():
    return chaos.create_policy('prod-readiness','PROD',[x['scenario_type'] for x in SCENARIOS],90,300,60,3600,'maker')

def exposure_policy(**kw):
    p=dict(rolling_window_hours=168,max_waiver_count=3,max_consecutive_waiver_releases=2,max_exposure_seconds=21600,max_exception_debt_points=100,remediation_sla_seconds=3600,escalation_after_seconds=60)
    p.update(kw)
    return svc.create_policy('prod-waiver-exposure','PROD',p['rolling_window_hours'],p['max_waiver_count'],p['max_consecutive_waiver_releases'],p['max_exposure_seconds'],p['max_exception_debt_points'],p['remediation_sla_seconds'],p['escalation_after_seconds'],'governance')

def new_waiver(owner='rem-owner',hours=1):
    return waiver.request_waiver('PROD','emergency release','known readiness exception','waiver://evidence','risk-owner',datetime.now(timezone.utc)-timedelta(seconds=2),datetime.now(timezone.utc)+timedelta(hours=hours),'requester',owner,'fix readiness regression')

def approve(w):
    waiver.approve_waiver(w['production_release_waiver_id'],'approver-a');return waiver.approve_waiver(w['production_release_waiver_id'],'approver-b')

def test_active_policy_requires_remediation_owner_even_through_legacy_4e_waiver_path():
    readiness_policy();exposure_policy()
    with pytest.raises(ValueError,match='REMEDIATION_OWNER_REQUIRED'):
        waiver.request_waiver('PROD','x','risk','waiver://x','risk-owner',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(hours=1),'requester')

def test_waiver_request_opens_mandatory_remediation_with_sla():
    readiness_policy();p=exposure_policy(remediation_sla_seconds=120)
    w=new_waiver()
    st=svc.status('PROD')
    assert len(st['remediations'])==1
    r=st['remediations'][0]
    assert r['waiver_id']==w['production_release_waiver_id'] and r['remediation_owner']=='rem-owner' and r['state']=='OPEN'
    assert (datetime.fromisoformat(r['due_at'])-datetime.fromisoformat(r['opened_at'])).total_seconds()==p['remediation_sla_seconds']

def test_rolling_waiver_budget_blocks_new_requests_after_limit():
    readiness_policy();exposure_policy(max_waiver_count=1,max_exception_debt_points=1000)
    new_waiver()
    with pytest.raises(ValueError,match='ROLLING_WAIVER_BUDGET_EXHAUSTED'):
        new_waiver('owner-2')

def test_consecutive_waiver_release_limit_blocks_further_exception_requests():
    readiness_policy();exposure_policy(max_waiver_count=10,max_consecutive_waiver_releases=2,max_exception_debt_points=1000)
    w=new_waiver();approve(w)
    assert waiver.authorize_release('PROD','manifest-1','deployer')['allowed']
    assert waiver.authorize_release('PROD','manifest-2','deployer')['allowed']
    d=svc.evaluate_debt('PROD','auditor')
    assert d['consecutive_waiver_releases']==2 and d['debt_state']=='BLOCKED'
    with pytest.raises(ValueError,match='CONSECUTIVE_WAIVER_LIMIT_REACHED'):new_waiver('owner-2')

def test_risk_exposure_time_budget_is_accounted_and_blocks_new_waiver():
    readiness_policy();exposure_policy(max_waiver_count=10,max_consecutive_waiver_releases=10,max_exposure_seconds=5,max_exception_debt_points=1000)
    w=new_waiver();approve(w)
    with SessionLocal() as s:
        x=s.get(JourneyRecoveryProductionReleaseWaiverRow,w['production_release_waiver_id']);x.starts_at=datetime.now(timezone.utc)-timedelta(seconds=30);s.commit()
    d=svc.evaluate_debt('PROD','auditor')
    assert d['exposure_seconds']>=5 and 'RISK_EXPOSURE_TIME_BUDGET_EXHAUSTED' in d['reason_codes']
    with pytest.raises(ValueError,match='RISK_EXPOSURE_TIME_BUDGET_EXHAUSTED'):new_waiver('owner-2')

def test_exception_debt_threshold_blocks_waiver_churn_before_raw_count_limit():
    readiness_policy();exposure_policy(max_waiver_count=10,max_consecutive_waiver_releases=10,max_exposure_seconds=999999,max_exception_debt_points=2)
    new_waiver()
    d=svc.evaluate_debt('PROD','auditor')
    assert d['debt_points']>=2 and 'EXCEPTION_DEBT_THRESHOLD_EXCEEDED' in d['reason_codes']
    with pytest.raises(ValueError,match='EXCEPTION_DEBT_THRESHOLD_EXCEEDED'):new_waiver('owner-2')

def test_overdue_remediation_escalates_and_resolution_requires_evidence():
    readiness_policy();exposure_policy(remediation_sla_seconds=60,escalation_after_seconds=1)
    new_waiver()
    with SessionLocal() as s:
        r=s.execute(select(JourneyRecoveryWaiverRemediationRow)).scalars().one();rid=r.waiver_remediation_id;r.due_at=datetime.now(timezone.utc)-timedelta(seconds=5);s.commit()
    out=svc.remediation_tick('PROD','scheduler');assert rid in out['escalated']
    r=svc.remediation(rid);assert r['state']=='ESCALATED' and r['escalation_level']==1
    with pytest.raises(ValueError,match='REMEDIATION_RESOLUTION_EVIDENCE_REQUIRED'):svc.resolve_remediation(rid,'','ops')
    r=svc.resolve_remediation(rid,'incident://fixed','ops');assert r['state']=='RESOLVED'

def test_waiver_release_and_remediation_actions_create_auditable_exposure_events():
    readiness_policy();exposure_policy(max_waiver_count=10,max_consecutive_waiver_releases=10,max_exception_debt_points=1000)
    w=new_waiver();approve(w);waiver.authorize_release('PROD','manifest-event','deployer')
    r=svc.status('PROD')['remediations'][0];svc.acknowledge_remediation(r['waiver_remediation_id'],'owner');svc.resolve_remediation(r['waiver_remediation_id'],'fix://done','owner')
    with SessionLocal() as s:
        kinds={x.event_type for x in s.execute(select(JourneyRecoveryWaiverExposureEventRow)).scalars().all()}
    assert {'WAIVER_REMEDIATION_OPENED','WAIVER_RELEASE_AUTHORIZED','REMEDIATION_ACKNOWLEDGED','REMEDIATION_RESOLVED'}<=kinds
    assert svc.status('PROD')['supplier_fact_unchanged'] is True
