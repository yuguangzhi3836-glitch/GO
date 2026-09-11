import os
from datetime import datetime, timezone, timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryTrustTransparencyLogRow, JourneyRecoveryCredentialIssuanceRow,
    JourneyRecoveryCredentialStatusDistributionRow, JourneyRecoveryMerkleCheckpointRow,
)
from go_hotel.journey.recovery_external_trust_witness import recovery_external_trust_witness_service as ext, witness_env_key
from go_hotel.journey.recovery_transparency_gossip import recovery_transparency_gossip_service as gossip
from go_hotel.journey.recovery_trust_plane_dr import recovery_trust_plane_dr_service as svc
from go_hotel.journey.recovery_federated_trust import recovery_federated_trust_service as ft


def seed_logs(n=4):
    t=datetime.now(timezone.utc)
    with SessionLocal() as s:
        for i in range(1,n+1):
            h=f'{i:064x}'
            s.add(JourneyRecoveryTrustTransparencyLogRow(transparency_log_id=f'4c-log-{i}',sequence_no=i,event_type='TEST',subject_type='CREDENTIAL',subject_id='cred-4c',environment='PROD',payload_hash=h,previous_hash=None if i==1 else f'{i-1:064x}',entry_hash=h,evidence_reference=f'e://{i}',created_by='test',created_at=t,supplier_fact_unchanged=True))
        s.add(JourneyRecoveryCredentialIssuanceRow(credential_issuance_id='iss-4c',runtime_identity_id='runtime-4c',attestation_policy_id='p',credential_issuer_id='issuer',hardware_trust_root_id='root',runtime_attestation_evidence_id='att',environment='PROD',state='ISSUED',credential_id='cred-4c',credential_fingerprint='fp',eligibility_state='ELIGIBLE',predecessor_credential_id=None,requested_by='t',requested_at=t,issued_by='t',issued_at=t,revoked_at=None,supplier_fact_unchanged=True))
        s.add(JourneyRecoveryCredentialStatusDistributionRow(credential_status_distribution_id='status-4c',credential_id='cred-4c',environment='PROD',status='GOOD',status_version=1,this_update_at=t,next_update_at=t+timedelta(minutes=10),issuer_id='issuer',root_id='root',status_hash='c'*64,publication_state='PUBLISHED',evidence_reference='status://4c',published_by='test',published_at=t,supplier_fact_unchanged=True))
        s.commit()


def setup_independent_witnesses():
    seed_logs();cp=ext.create_checkpoint('PROD','test')
    ws=[]
    specs=[('a','AWS','aws-ap-southeast-1a','kms-a'),('b','GCP','gcp-asia-southeast1-a','kms-b')]
    for key,cloud,fd,ka in specs:
        w=ext.register_witness(f'w-{key}','PROD',f'w-{key}-key',f'wfp-{key}','test')
        os.environ[witness_env_key(f'w-{key}-key')]=f'secret-{key}'
        sig=ext.sign_for_engineering(f'w-{key}-key',cp['checkpoint_hash'])
        ext.cosign_checkpoint(cp['merkle_checkpoint_id'],w['external_trust_witness_id'],sig,f'witness://{key}')
        op=svc.register_operator(f'op-{key}',f'org://{key}',f'control-{key}',cloud,ka,'test')
        svc.bind_witness(w['external_trust_witness_id'],op['witness_operator_id'],f'region-{key}',fd,cloud,ka,f'bind://{key}','test')
        ws.append((w,op))
    pol=svc.create_independence_policy('prod-independence','PROD',2,2,2,2,1,'test')
    fed=gossip.create_witness_federation('prod-fed','PROD',[x[0]['external_trust_witness_id'] for x in ws],2,'test')
    assessment=svc.assess_federation(fed['witness_federation_id'],'test')
    return cp,ws,pol,fed,assessment


def test_same_operator_witnesses_do_not_count_as_independent_quorum():
    seed_logs();cp=ext.create_checkpoint('PROD','test')
    op=svc.register_operator('same-op','org://same','control-same','AWS','kms-same','test')
    ids=[]
    for i in (1,2):
        w=ext.register_witness(f'same-{i}','PROD',f'same-{i}-key',f'fp-{i}','test')
        os.environ[witness_env_key(f'same-{i}-key')]=f's{i}'
        ext.cosign_checkpoint(cp['merkle_checkpoint_id'],w['external_trust_witness_id'],ext.sign_for_engineering(f'same-{i}-key',cp['checkpoint_hash']),f'w://{i}')
        svc.bind_witness(w['external_trust_witness_id'],op['witness_operator_id'],f'r{i}',f'fd{i}','AWS','kms-same',f'b://{i}','test')
        ids.append(w['external_trust_witness_id'])
    svc.create_independence_policy('p','PROD',2,2,2,2,1,'test')
    fed=gossip.create_witness_federation('f','PROD',ids,2,'test')
    a=svc.assess_federation(fed['witness_federation_id'],'test')
    assert a['state']=='FAIL'
    assert a['effective_independent_quorum']==1
    assert 'OPERATOR_INDEPENDENCE_QUORUM_NOT_MET' in a['reason_codes']


def test_independent_operator_failure_domain_quorum_passes():
    _,_,_,fed,a=setup_independent_witnesses()
    assert a['state']=='PASS' and a['operator_count']==2 and a['cloud_provider_count']==2 and a['key_authority_count']==2
    assert a['effective_independent_quorum']==2 and fed['minimum_quorum']==2


def test_cross_operator_gossip_detects_split_view_and_opens_incident():
    cp,ws,_,_,_=setup_independent_witnesses()
    svc.publish_cross_operator_gossip(ws[0][1]['witness_operator_id'],cp['merkle_checkpoint_id'],'ap-southeast-1','g://a','test')
    with SessionLocal() as s:
        fake=JourneyRecoveryMerkleCheckpointRow(merkle_checkpoint_id='fake-4c',environment='PROD',tree_size=cp['tree_size'],root_hash='f'*64,first_sequence_no=1,last_sequence_no=cp['tree_size'],checkpoint_hash='e'*64,state='ACTIVE',created_by='test',created_at=datetime.now(timezone.utc),supplier_fact_unchanged=True)
        s.add(fake);s.commit()
    svc.publish_cross_operator_gossip(ws[1][1]['witness_operator_id'],'fake-4c','us-east-1','g://b','test')
    d=svc.detect_cross_operator_split_view('PROD',cp['tree_size'],'g://detect','test')
    assert d['state']=='OPEN' and d['severity']=='SEV1'
    assert set(d['affected_regions'])=={'ap-southeast-1','us-east-1'}


def test_checkpoint_archive_rebuild_is_publicly_verifiable(client):
    cp,_,_,_,_=setup_independent_witnesses()
    a=svc.archive_checkpoint(cp['merkle_checkpoint_id'],'archive://cold-storage/4c','test')
    assert a['state']=='VERIFIED'
    r=client.get('/v1/trust/transparency/archive/'+a['checkpoint_archive_id']+'/verify')
    assert r.status_code==200 and r.json()['data']['verified'] is True
    assert 'leaf_hashes' not in r.json()['data']


def test_open_region_disaster_forces_4a_fail_safe(monkeypatch):
    cp,_,_,_,_=setup_independent_witnesses()
    ext.create_policy('mr-prod','PROD',['ap-southeast-1','us-east-1'],2,300,'test')
    ext.publish_region_replica('PROD','ap-southeast-1','cred-4c',cp['merkle_checkpoint_id'],'r://sg','test')
    ext.publish_region_replica('PROD','us-east-1','cred-4c',cp['merkle_checkpoint_id'],'r://us','test')
    svc.open_disaster('PROD','REGION','us-east-1',['us-east-1'],'dr://region','test')
    monkeypatch.setattr(ft,'evaluate_admission',lambda *a,**k:{'decision':'ALLOW'})
    d=ext.evaluate_consensus('runtime-4c','cred-4c','PROD','cluster-a','test')
    assert d['decision']=='FAIL_SAFE_DENY'
    assert 'TRUST_PLANE_DISASTER_REGION_UNAVAILABLE' in d['reason_codes']


def test_provider_disaster_rebuild_requires_independent_witnesses():
    cp,_,_,fed,_=setup_independent_witnesses()
    a=svc.archive_checkpoint(cp['merkle_checkpoint_id'],'archive://provider-dr','test')
    inc=svc.open_disaster('PROD','PROVIDER','aws',['ap-southeast-1'],'dr://aws','test')
    b=svc.rebuild_from_archive(inc['trust_plane_disaster_incident_id'],a['checkpoint_archive_id'],'ap-southeast-1',fed['witness_federation_id'],'rebuild://aws','test')
    assert b['verification_state']=='VERIFIED' and b['witness_independence_assessment_id']


def test_disaster_completion_requires_every_affected_region_rebuilt():
    cp,_,_,fed,_=setup_independent_witnesses()
    a=svc.archive_checkpoint(cp['merkle_checkpoint_id'],'archive://multi','test')
    inc=svc.open_disaster('PROD','PROVIDER','cloud-x',['r1','r2'],'dr://multi','test')
    svc.rebuild_from_archive(inc['trust_plane_disaster_incident_id'],a['checkpoint_archive_id'],'r1',fed['witness_federation_id'],'rb://1','test')
    with pytest.raises(ValueError,match='ALL_AFFECTED_REGIONS_REQUIRE_VERIFIED_REBUILD'):
        svc.complete_disaster_recovery(inc['trust_plane_disaster_incident_id'],'test','complete://early')
    svc.rebuild_from_archive(inc['trust_plane_disaster_incident_id'],a['checkpoint_archive_id'],'r2',fed['witness_federation_id'],'rb://2','test')
    out=svc.complete_disaster_recovery(inc['trust_plane_disaster_incident_id'],'test','complete://ok')
    assert out['state']=='RECOVERED'


def test_drill_records_recovery_evidence_after_verified_rebuild():
    cp,_,_,fed,_=setup_independent_witnesses()
    a=svc.archive_checkpoint(cp['merkle_checkpoint_id'],'archive://drill','test')
    inc=svc.open_disaster('PROD','REGION','r-drill',['r-drill'],'drill://open','test',True)
    b=svc.rebuild_from_archive(inc['trust_plane_disaster_incident_id'],a['checkpoint_archive_id'],'r-drill',fed['witness_federation_id'],'drill://rebuild','test')
    svc.complete_disaster_recovery(inc['trust_plane_disaster_incident_id'],'test','drill://complete')
    d=svc.record_recovery_drill(inc['trust_plane_disaster_incident_id'],b['trust_plane_rebuild_id'],'drill://evidence','test')
    assert d['result']=='PASS' and d['recovery_time_seconds']>=0
