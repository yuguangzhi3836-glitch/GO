from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryChaosExecutionRow,JourneyRecoveryTrustPlaneDisasterIncidentRow,JourneyRecoveryProductionReadinessGateRow
from go_hotel.journey.recovery_trust_plane_chaos import recovery_trust_plane_chaos_service as svc, production_readiness_allows, SUPPORTED_SCENARIOS


def make_policy(required=None,score=90,rto=300,rpo=60,ttl=86400):
    return svc.create_policy('prod-chaos','PROD',required or SUPPORTED_SCENARIOS,score,rto,rpo,ttl,'test')

def scenario(st,**kw):return {'scenario_type':st,'fault_parameters':kw}

def good_campaign(required=None,**policy):
    p=make_policy(required=required,**policy)
    req=required or SUPPORTED_SCENARIOS
    c=svc.create_campaign('PROD','campaign-1',[scenario(x) for x in req],'test')
    svc.run_campaign(c['chaos_campaign_id'],'test','evidence://')
    return p,c

def test_policy_versions_and_supported_failure_catalog():
    p1=make_policy(['WITNESS_LOSS','REGION_LOSS'])
    p2=make_policy(['WITNESS_LOSS','REGION_LOSS'])
    assert p1['version_no']==1 and p2['version_no']==2 and p2['state']=='ACTIVE'
    with pytest.raises(ValueError,match='INVALID_CHAOS_SCENARIO_POLICY'):
        svc.create_policy('bad','PROD',['UNKNOWN_FAILURE'],90,10,0,60,'test')

def test_full_campaign_covers_witness_region_provider_checkpoint_archive_and_quorum():
    _,c=good_campaign()
    out=svc.assess_readiness(c['chaos_campaign_id'],'test')
    assert out['state']=='PASS' and out['readiness_score']==100
    assert set(out['scenario_coverage']['covered'])==set(SUPPORTED_SCENARIOS)

def test_witness_loss_recovery_failure_blocks_readiness():
    make_policy(['WITNESS_LOSS'])
    c=svc.create_campaign('PROD','witness-fail',[scenario('WITNESS_LOSS',required_quorum=2,remaining_independent_quorum=1,post_recovery_quorum=1)],'test')
    svc.run_campaign(c['chaos_campaign_id'],'test')
    a=svc.assess_readiness(c['chaos_campaign_id'],'test')
    assert a['state']=='FAIL' and 'CHAOS_RECOVERY_OR_SAFETY_ACTION_FAILED' in a['reason_codes']

def test_rto_and_rpo_targets_are_hard_readiness_gates():
    make_policy(['REGION_LOSS'],rto=30,rpo=5)
    c=svc.create_campaign('PROD','slow',[scenario('REGION_LOSS',rto_seconds=31,rpo_seconds=6)],'test')
    svc.run_campaign(c['chaos_campaign_id'],'test')
    a=svc.assess_readiness(c['chaos_campaign_id'],'test')
    assert 'RTO_TARGET_BREACHED' in a['reason_codes'] and 'RPO_TARGET_BREACHED' in a['reason_codes']

def test_missing_required_scenario_blocks_production_readiness():
    make_policy(['REGION_LOSS','PROVIDER_LOSS'])
    c=svc.create_campaign('PROD','missing',[scenario('REGION_LOSS')],'test')
    svc.run_campaign(c['chaos_campaign_id'],'test')
    a=svc.assess_readiness(c['chaos_campaign_id'],'test')
    assert a['state']=='FAIL' and a['scenario_coverage']['missing']==['PROVIDER_LOSS']

def test_stale_chaos_evidence_fails_assessment():
    _,c=good_campaign(required=['STALE_CHECKPOINT'],ttl=5)
    with SessionLocal() as s:
        x=s.execute(select(JourneyRecoveryChaosExecutionRow).where(JourneyRecoveryChaosExecutionRow.chaos_campaign_id==c['chaos_campaign_id'])).scalars().one()
        x.completed_at=datetime.now(timezone.utc)-timedelta(seconds=30);s.commit()
    a=svc.assess_readiness(c['chaos_campaign_id'],'test')
    assert a['state']=='FAIL' and 'CHAOS_EVIDENCE_STALE' in a['reason_codes']

def test_open_real_disaster_blocks_gate_even_after_passing_drill():
    _,c=good_campaign(required=['PROVIDER_LOSS'])
    a=svc.assess_readiness(c['chaos_campaign_id'],'test')
    with SessionLocal() as s:
        s.add(JourneyRecoveryTrustPlaneDisasterIncidentRow(trust_plane_disaster_incident_id='real-dr',environment='PROD',failure_scope='PROVIDER',failure_domain_key='cloud-x',affected_regions_json=['r1'],state='OPEN',severity='SEV1',drill_mode=False,evidence_reference='real://dr',opened_by='test',opened_at=datetime.now(timezone.utc),recovered_at=None,supplier_fact_unchanged=True));s.commit()
    g=svc.evaluate_gate(a['readiness_assessment_id'],'gate://blocked','checker')
    assert g['gate_state']=='BLOCKED' and 'OPEN_TRUST_PLANE_DISASTER' in g['reason_codes']
    assert production_readiness_allows('PROD') is False

def test_passing_gate_allows_prod_until_evidence_expires():
    _,c=good_campaign(required=['ARCHIVE_CORRUPTION'],ttl=60)
    a=svc.assess_readiness(c['chaos_campaign_id'],'test')
    g=svc.evaluate_gate(a['readiness_assessment_id'],'gate://pass','checker')
    assert g['gate_state']=='PASS' and production_readiness_allows('PROD') is True
    with SessionLocal() as s:
        x=s.get(JourneyRecoveryProductionReadinessGateRow,g['production_readiness_gate_id']);x.valid_until=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
    assert production_readiness_allows('PROD') is False
