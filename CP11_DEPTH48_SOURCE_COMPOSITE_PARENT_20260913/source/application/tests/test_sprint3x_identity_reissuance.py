import os,pytest
from datetime import datetime,timezone
from go_hotel.journey.recovery_runtime_telemetry_trust import recovery_runtime_telemetry_trust_service as trust,env_key
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as life
from go_hotel.journey.recovery_runtime_identity_reissuance import recovery_runtime_identity_reissuance_service as reissue,attestation_env_key
from go_hotel.journey.recovery_runtime_telemetry_governance import recovery_runtime_telemetry_governance_service as telemetry

def setup_identities():
    trust.create_policy('auto-x','PROD','sre','HIGH',2,120,300,True,True,{})
    w=trust.register_identity('workload-x','WORKLOAD','PROD','spiffe://go/prod/runtime-x','workload-x-k1','sre')
    c1=trust.register_identity('collector-x1','COLLECTOR','PROD','spiffe://go/prod/collector-x1','collector-x1-k1','sre')
    c2=trust.register_identity('collector-x2','COLLECTOR','PROD','spiffe://go/prod/collector-x2','collector-x2-k1','sre')
    for ref,val in [('collector-x1-k1','old-one'),('collector-x1-k2','new-one'),('collector-x2-k1','two'),('workload-x-k1','workload')]:os.environ[env_key(ref)]=val
    os.environ[attestation_env_key('attestor-x')]='attestor-secret'
    s1=telemetry.register_source('prom-x1','PROMETHEUS','PROD','ops',{'max_freshness_seconds':300,'min_request_count':1,'required_metric_fields':['request_count','error_count','slo_target']},'GOVERNED','prom://x1')
    s2=telemetry.register_source('otel-x2','OTEL','PROD','ops',{'max_freshness_seconds':300,'min_request_count':1,'required_metric_fields':['request_count','error_count','slo_target']},'GOVERNED','otel://x2')
    return w,c1,c2,s1,s2

def request_for(c1,break_glass=False):
    life.revoke_identity(c1['runtime_identity_id'],'KEY_COMPROMISE','e://revoke','security')
    return reissue.request(c1['runtime_identity_id'],'collector-x1-replacement','spiffe://go/prod/collector-x1-r2','collector-x1-k2','attestor-x','CREDENTIAL_RECOVERY','e://reissuance','maker',break_glass)

def attest(req,nonce='att-x-1'):
    kwargs=dict(request_id=req['identity_reissuance_request_id'],attestation_type='CLOUD_WORKLOAD',challenge_nonce=nonce,workload_measurement='sha256:approved-image',evidence_reference='attest://cloud/123')
    sig=reissue.sign_attestation_for_engineering('attestor-x',**kwargs)
    return reissue.submit_attestation(req['identity_reissuance_request_id'],'CLOUD_WORKLOAD',nonce,'sha256:approved-image','attest://cloud/123',sig,'attestor')

def sign_and_ingest(src,w,c,key_ref,seq,nonce):
    ts=datetime.now(timezone.utc);m={'request_count':1000,'error_count':0,'slo_target':.999,'latency_p95_ms':100}
    sig=trust.sign_for_engineering(key_ref,source_id=src['telemetry_source_id'],workload_identity_id=w['runtime_identity_id'],collector_identity_id=c['runtime_identity_id'],environment='PROD',nonce=nonce,sequence_no=seq,observed_at=ts,metrics=m)
    return trust.ingest_signed(src['telemetry_source_id'],w['runtime_identity_id'],c['runtime_identity_id'],'runtime-x',m,nonce,seq,ts,sig,'telemetry')

def test_revoked_identity_cannot_be_reactivated_directly_and_requires_reissuance():
    _,c1,_,_,_=setup_identities();life.revoke_identity(c1['runtime_identity_id'],'KEY_COMPROMISE','e://r','security')
    with pytest.raises(ValueError,match='REVOKED_IDENTITY_REQUIRES_REISSUANCE'): trust.set_identity_state(c1['runtime_identity_id'],'ACTIVE','admin')
    req=reissue.request(c1['runtime_identity_id'],'collector-x1-replacement','spiffe://go/prod/c-r2','collector-x1-k2','attestor-x','CREDENTIAL_RECOVERY','e://req','maker')
    assert req['state']=='REQUESTED';assert req['predecessor_identity_id']==c1['runtime_identity_id']

def test_attestation_signature_challenge_binding_and_replay_protection():
    _,c1,_,_,_=setup_identities();req=request_for(c1);out=attest(req,'nonce-a');assert out['attestation']['verification_state']=='VERIFIED';assert out['request']['state']=='ATTESTED'
    with pytest.raises(ValueError,match='ATTESTATION_REPLAY_DETECTED'): reissue.submit_attestation(req['identity_reissuance_request_id'],'CLOUD_WORKLOAD','nonce-a','sha256:approved-image','attest://cloud/123','bad','attestor')

def test_invalid_attestation_signature_is_blocked():
    _,c1,_,_,_=setup_identities();req=request_for(c1)
    with pytest.raises(ValueError,match='ATTESTATION_SIGNATURE_INVALID'): reissue.submit_attestation(req['identity_reissuance_request_id'],'CLOUD_WORKLOAD','nonce-b','sha256:approved-image','attest://cloud/123','bad','attestor')

def test_maker_checker_and_break_glass_require_explicit_approval_evidence():
    _,c1,_,_,_=setup_identities();req=request_for(c1,True);attest(req,'nonce-c')
    with pytest.raises(ValueError,match='MAKER_CHECKER_APPROVER_MUST_DIFFER'): reissue.approve(req['identity_reissuance_request_id'],'breakglass://SEC-1','maker')
    with pytest.raises(ValueError,match='BREAK_GLASS_APPROVAL_EVIDENCE_REQUIRED'): reissue.approve(req['identity_reissuance_request_id'],'ticket://SEC-1','checker')
    out=reissue.approve(req['identity_reissuance_request_id'],'breakglass://SEC-1','checker');assert out['state']=='APPROVED';assert out['break_glass'] is True

def test_issue_creates_new_identity_lineage_and_permanent_old_tombstone():
    _,c1,_,_,_=setup_identities();req=request_for(c1);attest(req,'nonce-d');reissue.approve(req['identity_reissuance_request_id'],'approval://CHG-1','checker');out=reissue.issue(req['identity_reissuance_request_id'],'issuer')
    assert out['replacement_identity']['state']=='ACTIVE';assert out['replacement_identity']['runtime_identity_id']!=c1['runtime_identity_id'];assert trust.identity(c1['runtime_identity_id'])['state']=='REVOKED'
    assert out['lineage']['predecessor_identity_id']==c1['runtime_identity_id'];assert out['tombstone']['terminal_state']=='REVOKED';assert out['tombstone']['replacement_identity_id']==out['replacement_identity']['runtime_identity_id']
    with pytest.raises(ValueError,match='REVOKED_IDENTITY_REQUIRES_REISSUANCE'):trust.set_identity_state(c1['runtime_identity_id'],'ACTIVE','admin')

def test_open_security_incident_must_be_contained_before_reissuance_issue():
    _,c1,_,_,_=setup_identities();inc=life.open_security_incident(c1['runtime_identity_id'],'SEV1','CREDENTIAL_EXFILTRATION',{'ref':'F-1'},'security',True)
    req=reissue.request(c1['runtime_identity_id'],'collector-x1-replacement','spiffe://go/prod/c-r2','collector-x1-k2','attestor-x','CREDENTIAL_RECOVERY','e://req','maker');attest(req,'nonce-e');reissue.approve(req['identity_reissuance_request_id'],'approval://CHG-2','checker')
    with pytest.raises(ValueError,match='SECURITY_INCIDENT_MUST_BE_CONTAINED_BEFORE_REISSUANCE'):reissue.issue(req['identity_reissuance_request_id'],'issuer')
    life.contain_incident(inc['telemetry_security_incident_id'],{'isolated':True},'security');assert reissue.issue(req['identity_reissuance_request_id'],'issuer')['request']['state']=='ISSUED'

def test_replacement_identity_rejoins_automation_quorum_only_after_new_signed_telemetry():
    w,c1,c2,s1,s2=setup_identities();life.revoke_identity(c1['runtime_identity_id'],'KEY_COMPROMISE','e://r','security')
    req=reissue.request(c1['runtime_identity_id'],'collector-x1-replacement','spiffe://go/prod/c-r2','collector-x1-k2','attestor-x','CREDENTIAL_RECOVERY','e://req','maker');attest(req,'nonce-f');reissue.approve(req['identity_reissuance_request_id'],'approval://CHG-3','checker');new=reissue.issue(req['identity_reissuance_request_id'],'issuer')['replacement_identity']
    sign_and_ingest(s2,w,c2,'collector-x2-k1',1,'telemetry-x2');assert trust.assess_trust('PROD')['state']=='HUMAN_REVIEW_ONLY'
    sign_and_ingest(s1,w,new,'collector-x1-k2',1,'telemetry-new');t=trust.assess_trust('PROD');assert t['state']=='ALLOW_AUTOMATION';assert t['verified_source_count']==2

def test_reissuance_status_exposes_request_lineage_tombstone_and_cache_epoch():
    _,c1,_,_,_=setup_identities();req=request_for(c1);attest(req,'nonce-g');reissue.approve(req['identity_reissuance_request_id'],'approval://CHG-4','checker');reissue.issue(req['identity_reissuance_request_id'],'issuer');st=reissue.status('PROD')
    assert st['reissuance_requests'][0]['state']=='ISSUED';assert len(st['lineage'])==1;assert len(st['tombstones'])==1;assert st['trust_cache_epoch']>=2;assert st['supplier_fact_unchanged'] is True
