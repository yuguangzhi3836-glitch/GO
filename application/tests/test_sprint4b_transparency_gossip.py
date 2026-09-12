import os
from datetime import datetime, timezone, timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryTrustTransparencyLogRow, JourneyRecoveryCredentialIssuanceRow, JourneyRecoveryCredentialStatusDistributionRow
from go_hotel.journey.recovery_external_trust_witness import recovery_external_trust_witness_service as ext, witness_env_key
from go_hotel.journey.recovery_transparency_gossip import recovery_transparency_gossip_service as svc
from go_hotel.journey.recovery_federated_trust import recovery_federated_trust_service as ft

def seed_logs(n=6):
    t=datetime.now(timezone.utc)
    with SessionLocal() as s:
        for i in range(1,n+1):
            h=f'{i:064x}'
            s.add(JourneyRecoveryTrustTransparencyLogRow(transparency_log_id=f'glog-{i}',sequence_no=i,event_type='TEST',subject_type='CREDENTIAL',subject_id='cred-4b',environment='PROD',payload_hash=h,previous_hash=None if i==1 else f'{i-1:064x}',entry_hash=h,evidence_reference=f'e://{i}',created_by='test',created_at=t,supplier_fact_unchanged=True))
        s.add(JourneyRecoveryCredentialIssuanceRow(credential_issuance_id='iss-4b',runtime_identity_id='runtime-4b',attestation_policy_id='p',credential_issuer_id='issuer',hardware_trust_root_id='root',runtime_attestation_evidence_id='att',environment='PROD',state='ISSUED',credential_id='cred-4b',credential_fingerprint='fp',eligibility_state='ELIGIBLE',predecessor_credential_id=None,requested_by='t',requested_at=t,issued_by='t',issued_at=t,revoked_at=None,supplier_fact_unchanged=True))
        s.add(JourneyRecoveryCredentialStatusDistributionRow(credential_status_distribution_id='st-4b',credential_id='cred-4b',environment='PROD',status='GOOD',status_version=1,this_update_at=t,next_update_at=t+timedelta(minutes=10),issuer_id='issuer',root_id='root',status_hash='b'*64,publication_state='PUBLISHED',evidence_reference='status://4b',published_by='test',published_at=t,supplier_fact_unchanged=True))
        s.commit()

def checkpoints_and_witnesses():
    seed_logs(4);old=ext.create_checkpoint('PROD','test')
    t=datetime.now(timezone.utc)
    with SessionLocal() as s:
        for i in range(5,7):
            h=f'{i:064x}'
            s.add(JourneyRecoveryTrustTransparencyLogRow(transparency_log_id=f'glog-{i}',sequence_no=i,event_type='TEST',subject_type='CREDENTIAL',subject_id='cred-4b',environment='PROD',payload_hash=h,previous_hash=f'{i-1:064x}',entry_hash=h,evidence_reference=f'e://{i}',created_by='test',created_at=t,supplier_fact_unchanged=True))
        s.commit()
    new=ext.create_checkpoint('PROD','test')
    witnesses=[]
    for k in ['a','b']:
        w=ext.register_witness(f'witness-{k}','PROD',f'witness-{k}-key',f'wfp-{k}','test')
        os.environ[witness_env_key(f'witness-{k}-key')]=f'secret-{k}'
        sig=ext.sign_for_engineering(f'witness-{k}-key',new['checkpoint_hash'])
        ext.cosign_checkpoint(new['merkle_checkpoint_id'],w['external_trust_witness_id'],sig,f'witness://{k}')
        witnesses.append(w)
    return old,new,witnesses

def test_consistency_proof_verifies_append_only_extension():
    old,new,_=checkpoints_and_witnesses();p=svc.create_consistency_proof(old['merkle_checkpoint_id'],new['merkle_checkpoint_id'],'test');v=svc.verify_consistency_proof(p['consistency_proof_id']);assert p['verification_state']=='VERIFIED' and v['verified'] is True and v['old_tree_size']==4 and v['new_tree_size']==6

def test_witness_federation_requires_valid_quorum():
    _,_,ws=checkpoints_and_witnesses();f=svc.create_witness_federation('prod-witnesses','PROD',[w['external_trust_witness_id'] for w in ws],2,'test');assert f['minimum_quorum']==2 and f['version_no']==1
    with pytest.raises(ValueError,match='INVALID_WITNESS_FEDERATION_QUORUM'):svc.create_witness_federation('bad','PROD',[ws[0]['external_trust_witness_id']],2,'test')

def test_gossip_same_checkpoint_does_not_open_incident():
    _,new,_=checkpoints_and_witnesses();svc.gossip_local_checkpoint(new['merkle_checkpoint_id'],'obs-sg','ap-southeast-1','g://sg');svc.gossip_local_checkpoint(new['merkle_checkpoint_id'],'obs-us','us-east-1','g://us');d=svc.detect_split_view('PROD',new['tree_size'],'g://detect','test');assert d['split_view_detected'] is False

def test_gossip_conflict_opens_sev1_incident_and_isolates_regions():
    _,new,_=checkpoints_and_witnesses();svc.gossip_local_checkpoint(new['merkle_checkpoint_id'],'obs-sg','ap-southeast-1','g://sg');svc.publish_gossip('PROD','obs-us','us-east-1',new['tree_size'],'f'*64,'e'*64,'g://us','test');d=svc.detect_split_view('PROD',new['tree_size'],'g://split','test');assert d['state']=='OPEN' and d['severity']=='SEV1';assert {x['region_key'] for x in svc.isolated_regions('PROD')}=={'ap-southeast-1','us-east-1'}

def test_isolated_region_forces_4a_admission_fail_safe(monkeypatch):
    _,new,_=checkpoints_and_witnesses();ext.create_policy('mr-prod','PROD',['ap-southeast-1','us-east-1'],1,300,'test');ext.publish_region_replica('PROD','ap-southeast-1','cred-4b',new['merkle_checkpoint_id'],'r://sg','test');ext.publish_region_replica('PROD','us-east-1','cred-4b',new['merkle_checkpoint_id'],'r://us','test');svc.gossip_local_checkpoint(new['merkle_checkpoint_id'],'obs-sg','ap-southeast-1','g://sg');svc.publish_gossip('PROD','obs-us','us-east-1',new['tree_size'],'f'*64,'e'*64,'g://us','test');svc.detect_split_view('PROD',new['tree_size'],'g://split','test');monkeypatch.setattr(ft,'evaluate_admission',lambda *a,**k:{'decision':'ALLOW'});d=ext.evaluate_consensus('runtime-4b','cred-4b','PROD','cluster-a','test');assert d['decision']=='FAIL_SAFE_DENY' and 'REGION_ISOLATED_BY_TRUST_RECOVERY' in d['reason_codes']

def test_recovery_requires_verified_consistency_and_witness_federation_quorum():
    old,new,ws=checkpoints_and_witnesses();p=svc.create_consistency_proof(old['merkle_checkpoint_id'],new['merkle_checkpoint_id'],'test');f=svc.create_witness_federation('prod-witnesses','PROD',[w['external_trust_witness_id'] for w in ws],2,'test');svc.gossip_local_checkpoint(new['merkle_checkpoint_id'],'obs-sg','ap-southeast-1','g://sg');svc.publish_gossip('PROD','obs-us','us-east-1',new['tree_size'],'f'*64,'e'*64,'g://us','test');inc=svc.detect_split_view('PROD',new['tree_size'],'g://split','test');r=svc.request_recovery(inc['split_view_incident_id'],'ap-southeast-1',new['merkle_checkpoint_id'],p['consistency_proof_id'],f['witness_federation_id'],'rec://sg','test');assert r['state']=='VERIFIED_FOR_REJOIN' and r['witness_quorum_count']==2

def test_region_rejoin_requires_recovery_and_resolves_after_all_regions_rejoin():
    old,new,ws=checkpoints_and_witnesses();p=svc.create_consistency_proof(old['merkle_checkpoint_id'],new['merkle_checkpoint_id'],'test');f=svc.create_witness_federation('prod-witnesses','PROD',[w['external_trust_witness_id'] for w in ws],2,'test');svc.gossip_local_checkpoint(new['merkle_checkpoint_id'],'obs-sg','ap-southeast-1','g://sg');svc.publish_gossip('PROD','obs-us','us-east-1',new['tree_size'],'f'*64,'e'*64,'g://us','test');inc=svc.detect_split_view('PROD',new['tree_size'],'g://split','test')
    for region in ['ap-southeast-1','us-east-1']:
        r=svc.request_recovery(inc['split_view_incident_id'],region,new['merkle_checkpoint_id'],p['consistency_proof_id'],f['witness_federation_id'],f'rec://{region}','test');svc.rejoin_region(r['trust_recovery_id'],'test')
    assert svc.incident(inc['split_view_incident_id'])['state']=='RESOLVED' and svc.isolated_regions('PROD')==[]

def test_public_consistency_proof_is_anonymous(client):
    old,new,_=checkpoints_and_witnesses();p=svc.create_consistency_proof(old['merkle_checkpoint_id'],new['merkle_checkpoint_id'],'test');r=client.get('/v1/trust/transparency/consistency/'+p['consistency_proof_id']);assert r.status_code==200 and r.json()['data']['verified'] is True
