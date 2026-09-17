"""Read-only verification of the archived, exact-byte live acceptance evidence."""
import base64, hashlib, json
from pathlib import Path
from cryptography.hazmat.primitives import serialization

r = Path(__file__).resolve().parent
def read(name): return json.loads((r/name).read_text())
def gitblob(data): return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
identities = {i['role']: i for i in read('identities.json')['identities']}
def verify(name, role, keyname, blob):
    data=(r/name).read_bytes(); assert gitblob(data)==blob, name
    obj=json.loads(data); pub=(r/keyname).read_bytes(); identity=identities[role]
    assert hashlib.sha256(pub).hexdigest()==identity['public_key_file_sha256']
    key=serialization.load_ssh_public_key(pub)
    assert hashlib.sha256(key.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).hexdigest()==identity['public_key_raw_sha256']
    unsigned=json.dumps({k:v for k,v in obj.items() if k!='signature'},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    sig=bytes.fromhex(obj['signature']) if role=='TASK' else base64.b64decode(obj['signature'],validate=True)
    key.verify(sig,unsigned)
    return obj, hashlib.sha256(data).hexdigest(), hashlib.sha256(unsigned).hexdigest()

t,th,tc=verify('task.json','TASK','task.pub','0c4611e8fc686f0c64e9883eedb34b81681a53ac')
e,eh,ec=verify('evidence.json','EVIDENCE','evidence.pub','6224da676ef60fd2f52e17dcb8150cd9c9181393')
q=read('request.json'); host=read('HOST_READBACK.json'); install=read('HOST_INSTALL.json')
assert t['task_id'].endswith('-'+hashlib.sha256(q['request_id'].encode()).hexdigest()[:12])
for k in ['task_id','nonce','action_id','environment']: assert t[k]==e[k]
assert e['source_commit_sha']==t['parameters']['source']['commit_sha']=='edd3500575d2f2b81298cc9273025e0a3b734897'
assert e['source_pr_number']==t['parameters']['source']['pr_number']=='183'
assert e['task_canonical_sha256']==tc and e['status']=='SUCCESS' and e['executor_result']=='TEST_PR_OK'
assert set(e['gate_results'])=={'source_commit','offline_build','isolated_runtime_checks','artifact_sealed'}
assert set(e['gate_results'].values())=={'PASS'} and e['artifact_durability']=='PROVEN'
assert e['application_health_proven'] is False and e['deployment_performed'] is False
assert host['artifact_resolve']=='PASS' and host['artifact_sha256']==e['artifact_package']['package_sha256']
assert host['artifact_bytes']==e['artifact_package']['package_bytes']==115702784
for k,v in host['archive_identity'].items(): assert e['artifact_package'][k]==v
assert e['built_image_id']==host['archive_identity']['image_id']
assert host['artifact_mode']==0o600 and host['artifact_owner']==[998,998]
assert len(host['ledger']['attempts'])==1 and host['ledger']['attempts'][0]['attempt_number']==1
assert len(host['ledger']['processed'])==1 and host['ledger']['processed'][0]['status']=='completed'
assert host['ledger']['processed'][0]['evidence_ref']=='bce4d64cddef7eed8143e6f65156cc7b73e8a352'
assert install['result']=='INSTALLED' and install['protected_before']==install['protected_after']
assert install['runtime_before']==install['runtime_after'] and host['timer']=='active'
for name,sha in host['module_sha256'].items(): assert sha==install['after'][name]['sha256']
external=read('EXTERNAL_ROLLBACK_SOURCE.json')
rt,_,_=verify('EXTERNAL_ROLLBACK_TASK.json','TASK','task.pub',external['task_blob'])
re,reh,_=verify('EXTERNAL_ROLLBACK_EVIDENCE.json','EVIDENCE','evidence.pub',external['evidence_blob'])
for k in ['task_id','nonce','action_id','environment']: assert rt[k]==re[k]
assert re['status']=='SUCCESS' and re['executor_result']=='ROLLBACK_OK'
result=dict(result='PASS_SCOPED',candidate_sha=e['source_commit_sha'],task_sha256=th,evidence_sha256=eh,
            task_and_evidence_signatures='PASS',request_task_binding='PASS',artifact_binding='PASS',
            host_artifact_readback='PASS',single_attempt='PASS',install_protected_files_unchanged='PASS',
            install_runtime_unchanged='PASS',later_runtime='CHANGED_DURING_SEPARATE_SIGNED_ROLLBACK_CHAIN',
            separate_rollback_signature='PASS',separate_rollback_evidence_sha256=reh,
            independent_review_claim='Prior C14/C13 cover exact PR185 source; these live checks are primary-agent verification.',
            historical_first_exception='UNAVAILABLE_NOT_RECONSTRUCTED',business_deployment_by_this_session=False)
(r/'ACCEPTANCE_VERIFICATION.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps(result,sort_keys=True))
