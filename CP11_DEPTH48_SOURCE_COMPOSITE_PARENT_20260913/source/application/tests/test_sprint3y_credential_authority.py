import os,pytest
from datetime import datetime,timezone
from go_hotel.journey.recovery_runtime_telemetry_trust import recovery_runtime_telemetry_trust_service as trust,env_key
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as life
from go_hotel.journey.recovery_runtime_identity_reissuance import recovery_runtime_identity_reissuance_service as reissue,attestation_env_key
from go_hotel.journey.recovery_runtime_telemetry_governance import recovery_runtime_telemetry_governance_service as telemetry
from go_hotel.journey.recovery_credential_authority import recovery_credential_authority_service as ca

def setup_base():
    trust.create_policy('auto-y','PROD','sre','MEDIUM',1,120,300,True,True,{})
    w=trust.register_identity('workload-y-old','WORKLOAD','PROD','spiffe://go/prod/workload-y-old','workload-y-old-k1','sre')
    c=trust.register_identity('collector-y-old','COLLECTOR','PROD','spiffe://go/prod/collector-y-old','collector-y-old-k1','sre')
    for ref,val in [('workload-y-old-k1','wo'),('collector-y-old-k1','co'),('workload-y-new-k1','wn'),('collector-y-new-k1','cn')]:os.environ[env_key(ref)]=val
    os.environ[attestation_env_key('attestor-y')]='att-y'
    src=telemetry.register_source('prom-y','PROMETHEUS','PROD','ops',{'max_freshness_seconds':300,'min_request_count':1,'required_metric_fields':['request_count','error_count','slo_target']},'GOVERNED','prom://y')
    root=ca.register_trust_root('root-y','CLOUD_TPM','HARDWARE_BACKED','rootfp-y','security')
    issuer=ca.register_issuer('issuer-y','GO_CREDENTIAL_CA','PROD',root['hardware_trust_root_id'],'issuer-key-y','security')
    return w,c,src,root,issuer

def replace_identity(identity,new_key,new_subject,new_key_ref,nonce):
    life.revoke_identity(identity['runtime_identity_id'],'ROTATE_TO_3Y','e://revoke/'+nonce,'security')
    req=reissue.request(identity['runtime_identity_id'],new_key,new_subject,new_key_ref,'attestor-y','3Y_CREDENTIALIZATION','e://reissue/'+nonce,'maker')
    kwargs=dict(request_id=req['identity_reissuance_request_id'],attestation_type='CLOUD_WORKLOAD',challenge_nonce=nonce,workload_measurement='sha256:approved-image',evidence_reference='attest://cloud/'+nonce)
    sig=reissue.sign_attestation_for_engineering('attestor-y',**kwargs)
    out=reissue.submit_attestation(req['identity_reissuance_request_id'],'CLOUD_WORKLOAD',nonce,'sha256:approved-image','attest://cloud/'+nonce,sig,'attestor')
    reissue.approve(req['identity_reissuance_request_id'],'approval://'+nonce,'checker')
    issued=reissue.issue(req['identity_reissuance_request_id'],'identity-issuer')
    return issued['replacement_identity'],out['attestation']

def create_policy(issuer,min_trust='HARDWARE_BACKED',quorum=2,key='prod-hw'):
    return ca.create_policy(key,'PROD','ANY',min_trust,['CLOUD_WORKLOAD','TPM','TEE'],quorum,[issuer['credential_issuer_id']],'security',{'production_admission':True})

def credential(identity,att,policy,issuer,verifiers=('v1','v2')):
    x=ca.request_issuance(identity['runtime_identity_id'],policy['attestation_policy_id'],issuer['credential_issuer_id'],att['runtime_attestation_evidence_id'],'maker')
    for v in verifiers: ca.verify(x['credential_issuance_id'],v,'PASS','verify://'+v)
    return ca.issue(x['credential_issuance_id'],'credential-issuer')['issuance']

def signed_ingest(src,w,c,key_ref,nonce):
    ts=datetime.now(timezone.utc);m={'request_count':1000,'error_count':0,'slo_target':.999,'latency_p95_ms':100}
    sig=trust.sign_for_engineering(key_ref,source_id=src['telemetry_source_id'],workload_identity_id=w['runtime_identity_id'],collector_identity_id=c['runtime_identity_id'],environment='PROD',nonce=nonce,sequence_no=1,observed_at=ts,metrics=m)
    return trust.ingest_signed(src['telemetry_source_id'],w['runtime_identity_id'],c['runtime_identity_id'],'runtime-y',m,nonce,1,ts,sig,'telemetry')

def test_policy_versioning_and_hardware_trust_class_gate():
    w,_,_,root,issuer=setup_base();new,att=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y1')
    p1=create_policy(issuer,'HIGH_ASSURANCE',1,'prod-y');p2=create_policy(issuer,'HARDWARE_BACKED',1,'prod-y')
    assert p1['version_no']==1 and p2['version_no']==2
    with pytest.raises(ValueError,match='HARDWARE_TRUST_CLASS_BELOW_POLICY'):ca.request_issuance(new['runtime_identity_id'],p1['attestation_policy_id'],issuer['credential_issuer_id'],att['runtime_attestation_evidence_id'],'maker')

def test_verifier_quorum_is_required_before_credential_issue():
    w,_,_,_,issuer=setup_base();new,att=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y2');p=create_policy(issuer,quorum=2)
    x=ca.request_issuance(new['runtime_identity_id'],p['attestation_policy_id'],issuer['credential_issuer_id'],att['runtime_attestation_evidence_id'],'maker');ca.verify(x['credential_issuance_id'],'v1','PASS','verify://v1')
    with pytest.raises(ValueError,match='VERIFIER_QUORUM_REQUIRED'):ca.issue(x['credential_issuance_id'],'issuer')
    out=ca.verify(x['credential_issuance_id'],'v2','PASS','verify://v2');assert out['issuance']['state']=='VERIFIED'

def test_issue_creates_eligible_credential_and_immutable_lineage_fact():
    w,_,_,_,issuer=setup_base();new,att=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y3');p=create_policy(issuer,quorum=1)
    cred=credential(new,att,p,issuer,('v1',));assert cred['state']=='ISSUED';assert cred['eligibility_state']=='ELIGIBLE';assert cred['credential_id'].startswith('go-cred-')
    st=ca.status('PROD');assert st['credential_issuances'][0]['credential_id']==cred['credential_id'];assert st['supplier_fact_unchanged'] is True

def test_active_3y_policy_gates_telemetry_quorum_until_both_identities_have_credentials():
    w,c,src,_,issuer=setup_base();wn,wa=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y4w');cn,cae=replace_identity(c,'collector-y-new','spiffe://go/prod/collector-y-new','collector-y-new-k1','att-y4c');p=create_policy(issuer,quorum=1)
    signed_ingest(src,wn,cn,'collector-y-new-k1','telemetry-y4')
    assert trust.assess_trust('PROD')['state']=='HUMAN_REVIEW_ONLY'
    credential(wn,wa,p,issuer,('v1',));assert trust.assess_trust('PROD')['state']=='HUMAN_REVIEW_ONLY'
    credential(cn,cae,p,issuer,('v2',));assert trust.assess_trust('PROD')['state']=='ALLOW_AUTOMATION'

def test_revocation_sync_removes_existing_credential_from_automation_eligibility():
    w,c,src,_,issuer=setup_base();wn,wa=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y5w');cn,cae=replace_identity(c,'collector-y-new','spiffe://go/prod/collector-y-new','collector-y-new-k1','att-y5c');p=create_policy(issuer,quorum=1)
    wc=credential(wn,wa,p,issuer,('v1',));cc=credential(cn,cae,p,issuer,('v2',));signed_ingest(src,wn,cn,'collector-y-new-k1','telemetry-y5');assert trust.assess_trust('PROD')['state']=='ALLOW_AUTOMATION'
    sync=ca.sync_revocations('ISSUER',issuer['credential_issuer_id'],'PROD',1,[cc['credential_id']],'crl://issuer-y/v1','security',False);assert cc['credential_id'] in sync['revoked_credential_ids'];assert trust.assess_trust('PROD')['state']=='HUMAN_REVIEW_ONLY'

def test_revoking_authority_propagates_to_all_issued_credentials():
    w,c,_,_,issuer=setup_base();wn,wa=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y6w');cn,cae=replace_identity(c,'collector-y-new','spiffe://go/prod/collector-y-new','collector-y-new-k1','att-y6c');p=create_policy(issuer,quorum=1);wc=credential(wn,wa,p,issuer,('v1',));cc=credential(cn,cae,p,issuer,('v2',))
    sync=ca.sync_revocations('ISSUER',issuer['credential_issuer_id'],'PROD',2,[],'crl://issuer-y/revoked','security',True);assert set(sync['revoked_credential_ids'])=={wc['credential_id'],cc['credential_id']};assert ca.issuer(issuer['credential_issuer_id'])['state']=='REVOKED'

def test_failed_verifier_rejects_issuance_and_cannot_be_issued():
    w,_,_,_,issuer=setup_base();new,att=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y7');p=create_policy(issuer,quorum=2)
    x=ca.request_issuance(new['runtime_identity_id'],p['attestation_policy_id'],issuer['credential_issuer_id'],att['runtime_attestation_evidence_id'],'maker');out=ca.verify(x['credential_issuance_id'],'verifier-bad','FAIL','verify://fail');assert out['issuance']['state']=='REJECTED'
    with pytest.raises(ValueError,match='VERIFIER_QUORUM_REQUIRED|NOT_VERIFIABLE'):ca.issue(x['credential_issuance_id'],'issuer')

def test_status_exposes_root_issuer_policy_credentials_and_revocation_sync():
    w,_,_,root,issuer=setup_base();new,att=replace_identity(w,'workload-y-new','spiffe://go/prod/workload-y-new','workload-y-new-k1','att-y8');p=create_policy(issuer,quorum=1);cred=credential(new,att,p,issuer,('v1',));ca.sync_revocations('ISSUER',issuer['credential_issuer_id'],'PROD',3,[cred['credential_id']],'crl://v3','security',False);st=ca.status('PROD')
    assert st['trust_roots'][0]['hardware_trust_root_id']==root['hardware_trust_root_id'];assert st['issuers'][0]['credential_issuer_id']==issuer['credential_issuer_id'];assert st['policies'][0]['attestation_policy_id']==p['attestation_policy_id'];assert len(st['revocation_syncs'])==1
