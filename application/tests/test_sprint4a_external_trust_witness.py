import os
from datetime import datetime, timezone, timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryTrustTransparencyLogRow, JourneyRecoveryCredentialIssuanceRow, JourneyRecoveryCredentialStatusDistributionRow
from go_hotel.journey.recovery_external_trust_witness import recovery_external_trust_witness_service as svc, witness_env_key
from go_hotel.journey.recovery_federated_trust import recovery_federated_trust_service as ft

def seed():
    t=datetime.now(timezone.utc)
    with SessionLocal() as s:
        for i in range(1,6):
            h=f'{i:064x}'
            s.add(JourneyRecoveryTrustTransparencyLogRow(transparency_log_id=f'log-{i}',sequence_no=i,event_type='TEST',subject_type='CREDENTIAL',subject_id='cred-4a',environment='PROD',payload_hash=h,previous_hash=None if i==1 else f'{i-1:064x}',entry_hash=h,evidence_reference=f'e://{i}',created_by='test',created_at=t,supplier_fact_unchanged=True))
        s.add(JourneyRecoveryCredentialIssuanceRow(credential_issuance_id='iss-4a',runtime_identity_id='runtime-4a',attestation_policy_id='p',credential_issuer_id='issuer',hardware_trust_root_id='root',runtime_attestation_evidence_id='att',environment='PROD',state='ISSUED',credential_id='cred-4a',credential_fingerprint='fp',eligibility_state='ELIGIBLE',predecessor_credential_id=None,requested_by='t',requested_at=t,issued_by='t',issued_at=t,revoked_at=None,supplier_fact_unchanged=True))
        s.add(JourneyRecoveryCredentialStatusDistributionRow(credential_status_distribution_id='st-4a',credential_id='cred-4a',environment='PROD',status='GOOD',status_version=1,this_update_at=t,next_update_at=t+timedelta(minutes=10),issuer_id='issuer',root_id='root',status_hash='a'*64,publication_state='PUBLISHED',evidence_reference='status://4a',published_by='test',published_at=t,supplier_fact_unchanged=True))
        s.commit()

def witnessed_checkpoint():
    seed();cp=svc.create_checkpoint('PROD','test');w=svc.register_witness('witness-a','PROD','witness-a-key','wfpa','test');os.environ[witness_env_key('witness-a-key')]='secret-a';sig=svc.sign_for_engineering('witness-a-key',cp['checkpoint_hash']);svc.cosign_checkpoint(cp['merkle_checkpoint_id'],w['external_trust_witness_id'],sig,'witness://a');return cp

def test_merkle_checkpoint_and_inclusion_proof_verify():
    seed();cp=svc.create_checkpoint('PROD','test');p=svc.inclusion_proof(3,cp['merkle_checkpoint_id']);assert cp['tree_size']==5 and p['verified'] is True and p['root_hash']==cp['root_hash']

def test_wrong_witness_signature_is_rejected():
    seed();cp=svc.create_checkpoint('PROD','test');w=svc.register_witness('witness-a','PROD','witness-a-key','wfpa','test');os.environ[witness_env_key('witness-a-key')]='secret-a'
    with pytest.raises(ValueError,match='INVALID_WITNESS_SIGNATURE'):svc.cosign_checkpoint(cp['merkle_checkpoint_id'],w['external_trust_witness_id'],'bad','e://bad')

def test_valid_external_witness_cosigns_checkpoint():
    cp=witnessed_checkpoint();pub=svc.public_checkpoint('PROD');assert pub['checkpoint_hash']==cp['checkpoint_hash'] and pub['witness_count']==1

def test_consistent_regions_allow_when_witness_quorum_and_local_admission_pass(monkeypatch):
    cp=witnessed_checkpoint();svc.create_policy('mr-prod','PROD',['ap-southeast-1','us-east-1'],1,300,'test');svc.publish_region_replica('PROD','ap-southeast-1','cred-4a',cp['merkle_checkpoint_id'],'rep://sg','test');svc.publish_region_replica('PROD','us-east-1','cred-4a',cp['merkle_checkpoint_id'],'rep://us','test')
    monkeypatch.setattr(ft,'evaluate_admission',lambda *a,**k:{'decision':'ALLOW'})
    d=svc.evaluate_consensus('runtime-4a','cred-4a','PROD','cluster-a','test');assert d['decision']=='ALLOW' and d['consensus_state']=='CONSISTENT' and d['witness_count']==1

def test_split_view_is_fail_safe_deny_even_if_one_region_good(monkeypatch):
    cp=witnessed_checkpoint();svc.create_policy('mr-prod','PROD',['ap-southeast-1','us-east-1'],1,300,'test');svc.publish_region_replica('PROD','ap-southeast-1','cred-4a',cp['merkle_checkpoint_id'],'rep://sg','test');svc.publish_region_replica('PROD','us-east-1','cred-4a',cp['merkle_checkpoint_id'],'rep://us','test',status_override='REVOKED')
    monkeypatch.setattr(ft,'evaluate_admission',lambda *a,**k:{'decision':'ALLOW'})
    d=svc.evaluate_consensus('runtime-4a','cred-4a','PROD','cluster-a','test');assert d['decision']=='FAIL_SAFE_DENY' and d['split_view_detected'] is True and 'SPLIT_VIEW_DETECTED' in d['reason_codes']

def test_missing_region_is_fail_safe_deny(monkeypatch):
    cp=witnessed_checkpoint();svc.create_policy('mr-prod','PROD',['ap-southeast-1','us-east-1'],1,300,'test');svc.publish_region_replica('PROD','ap-southeast-1','cred-4a',cp['merkle_checkpoint_id'],'rep://sg','test');monkeypatch.setattr(ft,'evaluate_admission',lambda *a,**k:{'decision':'ALLOW'})
    d=svc.evaluate_consensus('runtime-4a','cred-4a','PROD','cluster-a','test');assert d['decision']=='FAIL_SAFE_DENY' and 'REGION_REPLICA_MISSING' in d['reason_codes']

def test_witness_quorum_not_met_denies(monkeypatch):
    seed();cp=svc.create_checkpoint('PROD','test');svc.create_policy('mr-prod','PROD',['ap-southeast-1','us-east-1'],1,300,'test');svc.publish_region_replica('PROD','ap-southeast-1','cred-4a',cp['merkle_checkpoint_id'],'rep://sg','test');svc.publish_region_replica('PROD','us-east-1','cred-4a',cp['merkle_checkpoint_id'],'rep://us','test');monkeypatch.setattr(ft,'evaluate_admission',lambda *a,**k:{'decision':'ALLOW'})
    d=svc.evaluate_consensus('runtime-4a','cred-4a','PROD','cluster-a','test');assert d['decision']=='FAIL_SAFE_DENY' and 'WITNESS_QUORUM_NOT_MET' in d['reason_codes']

def test_public_merkle_endpoints_are_anonymous(client):
    cp=witnessed_checkpoint();r=client.get('/v1/trust/transparency/merkle/checkpoint');assert r.status_code==200 and r.json()['data']['witness_count']==1
    p=client.get('/v1/trust/transparency/merkle/proof/2?checkpoint_id='+cp['merkle_checkpoint_id']);assert p.status_code==200 and p.json()['data']['verified'] is True
