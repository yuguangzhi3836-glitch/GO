"""Verify original Git blobs, separate signing identities and exact live bindings."""
import base64, datetime, hashlib, json, pathlib, sys
from cryptography.hazmat.primitives import serialization

ROOT=pathlib.Path(__file__).resolve().parent
KEYS=ROOT.parents[1]/'hk-shared-repair/live-acceptance'
sys.path.insert(0,str(ROOT.parent/'repair/control-plane/boss-deploy-request-v1'))
import go_deploy_request as gate
IDENTITIES={i['role']:i for i in json.loads((KEYS/'identities.json').read_text())['identities']}
CONTRACT=json.loads((ROOT.parent/'admission/CANDIDATE_CONTRACT.json').read_text())
CONTRACT_SHA='23d78ea846b21ace5318335eacb2a75826db5ff56cd925c8f8c58f6a83babed6'

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def original(mode,role):
    record=json.loads((ROOT/(mode+'_'+role+'_FETCH.json')).read_text());doc=json.loads(record['content'])
    raw=record['content'].encode();options=[raw,raw+b'\n',raw.rstrip(b'\r\n'),canonical(doc),canonical(doc)+b'\n']
    raw=next(x for x in options if blob(x)==record['blob'])
    (ROOT/(mode+'_'+role+'.json')).write_bytes(raw)
    return doc,hashlib.sha256(raw).hexdigest(),record['blob']
def public(role):
    raw=(KEYS/('task.pub' if role=='TASK' else 'evidence.pub')).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==IDENTITIES[role]['public_key_file_sha256']
    key=serialization.load_ssh_public_key(raw)
    assert hashlib.sha256(key.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).hexdigest()==IDENTITIES[role]['public_key_raw_sha256']
    return key

mode=sys.argv[1];task,tasksha,taskblob=original(mode,'TASK');evidence,evsha,evblob=original(mode,'EVIDENCE')
tk,ek=public('TASK'),public('EVIDENCE');at=datetime.datetime.now(datetime.timezone.utc)
gate.verify_signed(task,tk,'hex');gate.verify_signed(evidence,ek,'base64')
for field in ['task_id','nonce','action_id','environment']:assert task[field]==evidence[field]
if mode=='DEPLOY':
    fact=gate.rollback_source_proof(task,evidence,tk,ek)
    assert fact['migration_required'] is True
else:
    age=1800 if mode=='CANARY' else 300
    gate.proof(task,evidence,task['action_id'],tk,ek,at,age)
params=task['parameters'];expected=CONTRACT['expected_current_image_id'] if mode in ['CANARY','PREFLIGHT','DEPLOY'] else CONTRACT['candidate']['image_id']
assert params['expected_current_image_id']==expected
if mode=='PREFLIGHT':
    assert params['candidate_image_id']==CONTRACT['expected_current_image_id']
    assert 'candidate_contract_sha256' not in params
else:
    assert params['candidate_image_id']==CONTRACT['candidate']['image_id']
    assert params['candidate_contract_sha256']==CONTRACT_SHA
    if mode in ['CANARY','DEPLOY']:assert params['candidate_package_sha256']==CONTRACT['candidate']['package_sha256']
result={'schema':'go.issue103.live-pair-verification.v1','mode':mode,'status':'PASS_SCOPED','verified_at':at.isoformat(),
        'task_id':task['task_id'],'task_sha256':tasksha,'task_git_blob':taskblob,
        'evidence_sha256':evsha,'evidence_git_blob':evblob,'completed_at':evidence['completed_at'],
        'source_sha':CONTRACT['candidate']['source_commit'],'candidate_contract_sha256':CONTRACT_SHA,
        'signature_and_binding':'PASS','gate_results':evidence['gate_results'],
        'deployment_complete':False,'production':'HOLD','real_supplier_connections':'HOLD'}
(ROOT/(mode+'_VERIFICATION.json')).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps(result,sort_keys=True))
