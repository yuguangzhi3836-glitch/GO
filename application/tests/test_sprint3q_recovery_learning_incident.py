from datetime import datetime, timezone, timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryLearningKillSwitchRow,JourneyRecoveryLearningChangeRequestRow
from go_hotel.journey.recovery_learning_incident import recovery_learning_incident_service as svc
from go_hotel.journey.recovery_data_governance import recovery_data_governance_service as dg


def test_open_incident_creates_snapshot_and_forces_baseline():
    out=svc.open_incident('GLOBAL','*','SEV1','adaptive anomaly','admin-a')
    assert out['state']=='BASELINE_ONLY'
    assert out['rollback_snapshot']['snapshot_hash']
    assert out['rollback_snapshot']['baseline_parameters']['max_attempts']==8
    with SessionLocal() as s:
        ks=s.get(JourneyRecoveryLearningKillSwitchRow,out['kill_switch_id'])
        assert ks and ks.enabled is True


def test_resume_requires_postmortem_and_maker_checker():
    inc=svc.open_incident('VERTICAL','RAIL','SEV2','rail drift','admin-a')
    t=datetime.now(timezone.utc)
    with pytest.raises(ValueError,match='POSTMORTEM_REQUIRED'):
        svc.request_resume(inc['incident_id'],t-timedelta(minutes=1),t+timedelta(minutes=10),{},'admin-a')
    svc.add_postmortem(inc['incident_id'],'evidence://pm/rail','validated incident','bad calibration',['recalibrate'],'admin-a')
    cr=svc.request_resume(inc['incident_id'],t-timedelta(minutes=1),t+timedelta(minutes=10),{},'admin-a')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):
        svc.approve_resume(cr['change_request_id'],'admin-a')
    approved=svc.approve_resume(cr['change_request_id'],'admin-b')
    assert approved['state']=='APPROVED'


def test_execute_resume_rejected_outside_change_window():
    inc=svc.open_incident('ADAPTER','hotel_recovery_v1','SEV2','adapter issue','admin-a')
    svc.add_postmortem(inc['incident_id'],'evidence://pm/hotel','validated','adapter regression',[],'admin-a')
    t=datetime.now(timezone.utc)
    cr=svc.request_resume(inc['incident_id'],t+timedelta(hours=1),t+timedelta(hours=2),{},'admin-a')
    svc.approve_resume(cr['change_request_id'],'admin-b')
    with pytest.raises(ValueError,match='OUTSIDE_APPROVED_CHANGE_WINDOW'):
        svc.execute_resume(cr['change_request_id'],'admin-c',t)


def test_staged_resume_activates_narrower_blocks_before_releasing_global():
    inc=svc.open_incident('GLOBAL','*','SEV1','global learning incident','admin-a')
    svc.add_postmortem(inc['incident_id'],'evidence://pm/global','fixed bad data feed','bad source',['quarantine source'],'admin-a')
    t=datetime.now(timezone.utc)
    plan={'stage':'GLOBAL_TO_VERTICAL','remaining_block_scopes':[{'scope_type':'VERTICAL','scope_key':'RAIL'},{'scope_type':'ADAPTER','scope_key':'hotel_recovery_v1'}]}
    cr=svc.request_resume(inc['incident_id'],t-timedelta(minutes=1),t+timedelta(minutes=10),plan,'admin-a')
    svc.approve_resume(cr['change_request_id'],'admin-b')
    done=svc.execute_resume(cr['change_request_id'],'admin-c',t)
    assert done['state']=='EXECUTED'
    with SessionLocal() as s:
        global_ks=s.query(JourneyRecoveryLearningKillSwitchRow).filter_by(scope_type='GLOBAL',scope_key='*').one();assert global_ks.enabled is False
        rail=s.query(JourneyRecoveryLearningKillSwitchRow).filter_by(scope_type='VERTICAL',scope_key='RAIL').one();assert rail.enabled is True
        hotel=s.query(JourneyRecoveryLearningKillSwitchRow).filter_by(scope_type='ADAPTER',scope_key='hotel_recovery_v1').one();assert hotel.enabled is True


def test_close_requires_executed_change_and_closure_evidence():
    inc=svc.open_incident('VERTICAL','FLIGHT','SEV2','flight learning issue','admin-a')
    svc.add_postmortem(inc['incident_id'],'evidence://pm/flight','fixed','bad cohort',['guardrail'],'admin-a')
    t=datetime.now(timezone.utc);cr=svc.request_resume(inc['incident_id'],t-timedelta(minutes=1),t+timedelta(minutes=10),{},'admin-a');svc.approve_resume(cr['change_request_id'],'admin-b');svc.execute_resume(cr['change_request_id'],'admin-c',t)
    with pytest.raises(ValueError,match='CLOSURE_EVIDENCE_REQUIRED'):svc.close_incident(inc['incident_id'],'admin-d','')
    closed=svc.close_incident(inc['incident_id'],'admin-d','evidence://closure/flight')
    assert closed['state']=='CLOSED';assert closed['postmortem_evidence']['closure_evidence_reference']=='evidence://closure/flight'

def test_direct_resume_is_blocked_when_incident_owns_kill_switch():
    inc=svc.open_incident('ADAPTER','rail_recovery_v1','SEV2','controlled stop','admin-a')
    with pytest.raises(ValueError,match='CHANGE_CONTROL_REQUIRED'):
        dg.set_kill_switch('ADAPTER','rail_recovery_v1',False,'admin-z','manual bypass')
