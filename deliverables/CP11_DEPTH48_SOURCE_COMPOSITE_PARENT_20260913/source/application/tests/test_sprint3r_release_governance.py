from datetime import datetime, timezone, timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryEnvironmentBindingRow
from go_hotel.journey.recovery_release_governance import recovery_release_governance_service as svc
from go_hotel.journey.recovery_strategy_governance import recovery_strategy_governance_service as strategy
from go_hotel.journey.recovery_learning_incident import recovery_learning_incident_service as incidents


def cfg(key='recovery.policy',payload=None,actor='admin-a'):
    return svc.create_config_version(key,'GENERIC','GLOBAL','*',actor,payload or {'max_attempts':8})

def promote_to_staging(c,requester='admin-a',approver='admin-b',promoter='admin-c'):
    m=svc.create_manifest('DEV','STAGING',[c['config_version_id']],requester)
    svc.dry_run(m['release_manifest_id'],requester)
    svc.approve(m['release_manifest_id'],approver)
    return svc.promote(m['release_manifest_id'],promoter)

def promote_to_prod(c,rollback=None,requester='admin-a',approver='admin-b',promoter='admin-c'):
    m=svc.create_manifest('STAGING','PROD',[c['config_version_id']],requester,rollback)
    svc.dry_run(m['release_manifest_id'],requester)
    svc.attach_staging_evidence(m['release_manifest_id'],'evidence://staging/pass','staging checks passed',requester)
    svc.approve(m['release_manifest_id'],approver)
    return svc.promote(m['release_manifest_id'],promoter)


def test_immutable_config_versions_increment_and_dev_binding_tracks_latest():
    a=cfg(payload={'max_attempts':8});b=cfg(payload={'max_attempts':10})
    assert a['version_number']==1 and b['version_number']==2
    assert a['content_hash']!=b['content_hash']
    dev=[x for x in svc.bindings('DEV') if x['config_key']=='recovery.policy'][0]
    assert dev['active_config_version_id']==b['config_version_id']
    assert dev['previous_config_version_id']==a['config_version_id']
    assert svc.config(a['config_version_id'])['payload']['max_attempts']==8


def test_dry_run_requires_source_environment_binding_match():
    a=cfg();m=svc.create_manifest('DEV','STAGING',[a['config_version_id']],'admin-a')
    assert svc.dry_run(m['release_manifest_id'],'admin-a')['passed'] is True
    cfg(payload={'max_attempts':12})
    stale=svc.create_manifest('DEV','STAGING',[a['config_version_id']],'admin-a')
    with pytest.raises(ValueError,match='RELEASE_DRY_RUN_FAILED'):svc.dry_run(stale['release_manifest_id'],'admin-a')


def test_prod_requires_staging_evidence_and_maker_checker():
    c=cfg();promote_to_staging(c)
    m=svc.create_manifest('STAGING','PROD',[c['config_version_id']],'admin-a')
    svc.dry_run(m['release_manifest_id'],'admin-a')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve(m['release_manifest_id'],'admin-a')
    with pytest.raises(ValueError,match='STAGING_EVIDENCE_REQUIRED'):svc.approve(m['release_manifest_id'],'admin-b')
    svc.attach_staging_evidence(m['release_manifest_id'],'evidence://staging/1','passed','admin-a')
    svc.approve(m['release_manifest_id'],'admin-b');done=svc.promote(m['release_manifest_id'],'admin-c')
    assert done['state']=='PROMOTED';prod=[x for x in svc.bindings('PROD') if x['config_key']==c['config_key']][0];assert prod['active_config_version_id']==c['config_version_id']


def test_explicit_rollback_target_restores_previous_prod_manifest():
    v1=cfg(payload={'max_attempts':8});promote_to_staging(v1);p1=promote_to_prod(v1)
    v2=cfg(payload={'max_attempts':11});promote_to_staging(v2);p2=promote_to_prod(v2,rollback=p1['release_manifest_id'])
    prod=[x for x in svc.bindings('PROD') if x['config_key']==v2['config_key']][0];assert prod['active_config_version_id']==v2['config_version_id']
    rolled=svc.rollback(p2['release_manifest_id'],'admin-d');assert rolled['state']=='ROLLED_BACK'
    prod=[x for x in svc.bindings('PROD') if x['config_key']==v2['config_key']][0];assert prod['active_config_version_id']==v1['config_version_id']


def test_drift_detection_is_observational_and_does_not_auto_mutate_expected_binding():
    c=cfg();promote_to_staging(c);promote_to_prod(c)
    before=[x for x in svc.bindings('PROD') if x['config_key']==c['config_key']][0]
    out=svc.check_drift('PROD',{c['config_key']:{'config_version_id':'unexpected','binding_hash':'bad'}},'admin-a')
    assert out['drift_detected'] is True and out['action']=='BLOCK_PROMOTION_AND_RECONCILE'
    after=[x for x in svc.bindings('PROD') if x['config_key']==c['config_key']][0]
    assert after['active_config_version_id']==before['active_config_version_id']
    assert after['drift_status']=='DRIFTED' and out['supplier_fact_unchanged'] is True


def test_strategy_calibration_or_incident_change_can_be_snapshotted_as_release_config():
    sid=strategy.create('release-source',min_sample=20,min_confidence=.8)
    strategy.approve(sid,'admin-b')
    sver=svc.create_config_version('recovery.strategy.release','STRATEGY','GLOBAL','*','admin-a',source_ref_kind='STRATEGY',source_ref_id=sid)
    assert sver['payload']['strategy_version_id']==sid and sver['source_ref_kind']=='STRATEGY'

    inc=incidents.open_incident('VERTICAL','RAIL','SEV2','release controlled resume','admin-a')
    incidents.add_postmortem(inc['incident_id'],'evidence://pm/3r','fixed','config issue',['release guard'],'admin-a')
    t=datetime.now(timezone.utc);cr=incidents.request_resume(inc['incident_id'],t-timedelta(minutes=1),t+timedelta(minutes=5),{},'admin-a');incidents.approve_resume(cr['change_request_id'],'admin-b');incidents.execute_resume(cr['change_request_id'],'admin-c',t)
    cver=svc.create_config_version('recovery.incident.change','INCIDENT_CHANGE','VERTICAL','RAIL','admin-d',source_ref_kind='INCIDENT_CHANGE',source_ref_id=cr['change_request_id'])
    assert cver['payload']['change_request_id']==cr['change_request_id'] and cver['payload']['execution_result']['adaptive_effect']=='NORMAL_GOVERNANCE'
