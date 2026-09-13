import os,pytest
from datetime import datetime,timezone,timedelta
from go_hotel.journey.recovery_runtime_telemetry_trust import recovery_runtime_telemetry_trust_service as trust,env_key
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as life
from go_hotel.journey.recovery_runtime_identity_reissuance import recovery_runtime_identity_reissuance_service as reissue,attestation_env_key
from go_hotel.journey.recovery_runtime_telemetry_governance import recovery_runtime_telemetry_governance_service as telemetry
from go_hotel.journey.recovery_credential_authority import recovery_credential_authority_service as ca
from go_hotel.journey.recovery_federated_trust import recovery_federated_trust_service as ft
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryCredentialStatusDistributionRow

def base():
    trust.create_policy('auto-z','PROD','sre','MEDIUM',1,120,300,True,True,{})
    w=trust.register_identity('w-z-old','WORKLOAD','PROD','spiffe://go/prod/w-z-old','w-z-old-k1','sre')
    c=trust.register_identity('c-z-old','COLLECTOR','PROD','spiffe://go/prod/c-z-old','c-z-old-k1','sre')
    for ref,val in [('w-z-old-k1','woz'),('c-z-old-k1','coz'),('w-z-new-k1','wnz'),('c-z-new-k1','cnz')]:os.environ[env_key(ref)]=val
    os.environ[attestation_env_key('attestor-z')]='att-z'
    src=telemetry.register_source('prom-z','PROMETHEUS','PROD','ops',{'max_freshness_seconds':300,'min_request_count':1,'required_metric_fields':['request_count','error_count','slo_target']},'GOVERNED','prom://z')
    root=ca.register_trust_root('root-z','CLOUD_TPM','HARDWARE_BACKED','rootfp-z','security')
    issuer=ca.register_issuer('issuer-z','GO_CREDENTIAL_CA','PROD',root['hardware_trust_root_id'],'issuer-key-z','security')
    return w,c,src,root,issuer

def replace(identity,new_key,new_subject,new_key_ref,nonce):
    life.revoke_identity(identity['runtime_identity_id'],'ROTATE_TO_3Z','e://revoke/'+nonce,'security')
    req=reissue.request(identity['runtime_identity_id'],new_key,new_subject,new_key_ref,'attestor-z','3Z_CREDENTIALIZATION','e://reissue/'+nonce,'maker')
    kw=dict(request_id=req['identity_reissuance_request_id'],attestation_type='CLOUD_WORKLOAD',challenge_nonce=nonce,workload_measurement='sha256:approved-image',evidence_reference='attest://cloud/'+nonce)
    sig=reissue.sign_attestation_for_engineering('attestor-z',**kw)
    out=reissue.submit_attestation(req['identity_reissuance_request_id'],'CLOUD_WORKLOAD',nonce,'sha256:approved-image','attest://cloud/'+nonce,sig,'attestor')
    reissue.approve(req['identity_reissuance_request_id'],'approval://'+nonce,'checker')
    issued=reissue.issue(req['identity_reissuance_request_id'],'identity-issuer')
    return issued['replacement_identity'],out['attestation']

def policy_and_credential(identity,att,issuer,key):
    p=ca.create_policy(key,'PROD','ANY','HARDWARE_BACKED',['CLOUD_WORKLOAD'],1,[issuer['credential_issuer_id']],'security',{'production_admission':True})
    x=ca.request_issuance(identity['runtime_identity_id'],p['attestation_policy_id'],issuer['credential_issuer_id'],att['runtime_attestation_evidence_id'],'maker')
    ca.verify(x['credential_issuance_id'],'verifier-z','PASS','verify://z')
    return p,ca.issue(x['credential_issuance_id'],'credential-issuer')['issuance']

def signed(src,w,c,key_ref,nonce):
    ts=datetime.now(timezone.utc);m={'request_count':1000,'error_count':0,'slo_target':.999,'latency_p95_ms':100}
    sig=trust.sign_for_engineering(key_ref,source_id=src['telemetry_source_id'],workload_identity_id=w['runtime_identity_id'],collector_identity_id=c['runtime_identity_id'],environment='PROD',nonce=nonce,sequence_no=1,observed_at=ts,metrics=m)
    return trust.ingest_signed(src['telemetry_source_id'],w['runtime_identity_id'],c['runtime_identity_id'],'runtime-z',m,nonce,1,ts,sig,'telemetry')

def prepared_pair():
    w,c,src,root,issuer=base();wn,wa=replace(w,'w-z-new','spiffe://go/prod/w-z-new','w-z-new-k1','zw');cn,cea=replace(c,'c-z-new','spiffe://go/prod/c-z-new','c-z-new-k1','zc')
    _,wc=policy_and_credential(wn,wa,issuer,'prod-z-workload');_,cc=policy_and_credential(cn,cea,issuer,'prod-z-collector')
    fed=ft.register_federation('fed-z','PROD','*',root['hardware_trust_root_id'],'peerfp-z',1,'security')
    ap=ft.create_admission_policy('admit-z','PROD','*',300,[fed['trust_federation_id']],True,'security',{'consistent_across_clusters':True})
    return wn,cn,src,root,issuer,wc,cc,fed,ap

def test_public_status_is_unknown_before_publication_and_good_after():
    *_,wc,cc,fed,ap=prepared_pair();assert ft.public_credential_status(wc['credential_id'])['status']=='UNKNOWN'
    st=ft.publish_credential_status(wc['credential_id'],'GOOD','ocsp://z/w', 'status-publisher',300);pub=ft.public_credential_status(wc['credential_id'])
    assert pub['status']=='GOOD' and pub['fresh'] is True and st['status_version']==1

def test_transparency_log_checkpoint_is_append_only_chained():
    *_,wc,cc,fed,ap=prepared_pair();before=ft.transparency_checkpoint();ft.publish_credential_status(wc['credential_id'],'GOOD','status://w','publisher');after=ft.transparency_checkpoint()
    assert after['tree_size']>before['tree_size'] and after['root_entry_hash'] and after['append_only'] is True

def test_federated_admission_requires_fresh_good_status_and_transparency():
    wn,cn,src,root,issuer,wc,cc,fed,ap=prepared_pair();deny=ft.evaluate_admission(wn['runtime_identity_id'],'PROD','cluster-a');assert deny['decision']=='DENY' and 'STATUS_NOT_PUBLISHED' in deny['reason_codes']
    ft.publish_credential_status(wc['credential_id'],'GOOD','ocsp://w','publisher');allow=ft.evaluate_admission(wn['runtime_identity_id'],'PROD','cluster-a');assert allow['decision']=='ALLOW' and allow['transparency_log_id']

def test_stale_status_denies_admission():
    wn,cn,src,root,issuer,wc,cc,fed,ap=prepared_pair();st=ft.publish_credential_status(wc['credential_id'],'GOOD','ocsp://w','publisher',300)
    with SessionLocal() as s:
        row=s.get(JourneyRecoveryCredentialStatusDistributionRow,st['credential_status_distribution_id']);row.next_update_at=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
    # This direct mutation is allowed in ORM tests because immutable trigger is migration-level; decision still must reject stale evidence.
    deny=ft.evaluate_admission(wn['runtime_identity_id'],'PROD','cluster-a');assert deny['decision']=='DENY' and 'CREDENTIAL_STATUS_STALE' in deny['reason_codes']

def test_trust_assessment_requires_both_identity_statuses_when_3z_policy_active():
    wn,cn,src,root,issuer,wc,cc,fed,ap=prepared_pair();signed(src,wn,cn,'c-z-new-k1','telemetry-z1')
    ft.publish_credential_status(wc['credential_id'],'GOOD','status://w','publisher');assert trust.assess_trust('PROD')['state']=='HUMAN_REVIEW_ONLY'
    ft.publish_credential_status(cc['credential_id'],'GOOD','status://c','publisher');t=trust.assess_trust('PROD');assert t['state']=='ALLOW_AUTOMATION' and t['evidence']['federated_trust_gate'] is True

def test_issuer_compromise_fans_out_revoke_status_and_removes_quorum():
    wn,cn,src,root,issuer,wc,cc,fed,ap=prepared_pair();ft.publish_credential_status(wc['credential_id'],'GOOD','status://w','publisher');ft.publish_credential_status(cc['credential_id'],'GOOD','status://c','publisher');signed(src,wn,cn,'c-z-new-k1','telemetry-z2');assert trust.assess_trust('PROD')['state']=='ALLOW_AUTOMATION'
    inc=ft.report_issuer_compromise(issuer['credential_issuer_id'],'SEV1','incident://issuer-z','security');assert inc['fanout_count']==2
    assert ft.public_credential_status(wc['credential_id'])['status']=='REVOKED';assert trust.assess_trust('PROD')['state']=='HUMAN_REVIEW_ONLY'

def test_cluster_policy_consistency_and_status_surface():
    wn,cn,src,root,issuer,wc,cc,fed,ap=prepared_pair();ft.publish_credential_status(wc['credential_id'],'GOOD','status://w','publisher');d1=ft.evaluate_admission(wn['runtime_identity_id'],'PROD','cluster-a');d2=ft.evaluate_admission(wn['runtime_identity_id'],'PROD','cluster-b');assert d1['decision']==d2['decision']=='ALLOW'
    st=ft.status('PROD');assert st['federations'][0]['trust_federation_id']==fed['trust_federation_id'];assert st['transparency_checkpoint']['tree_size']>=1

def test_public_http_status_and_transparency_checkpoint_require_no_admin_auth(client):
    *_,wc,cc,fed,ap=prepared_pair();ft.publish_credential_status(wc['credential_id'],'GOOD','status://public','publisher')
    r=client.get('/v1/trust/credentials/'+wc['credential_id']+'/status');assert r.status_code==200;data=r.json()['data'];assert data['status']=='GOOD' and 'status_hash' in data and 'verification_key_ref' not in data
    cp=client.get('/v1/trust/transparency/checkpoint');assert cp.status_code==200 and cp.json()['data']['append_only'] is True
