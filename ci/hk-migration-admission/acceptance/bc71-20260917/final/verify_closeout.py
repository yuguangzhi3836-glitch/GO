"""Offline check of original signed deployment receipts and fixed host records."""
import base64, datetime as dt, hashlib, json
from pathlib import Path
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parent
def read(name): return json.loads((ROOT / name).read_text())
def canon(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()
identities = {v['role']:v for v in read('identities.json')['identities']}
keys = {}
for role, name in [('TASK','task.pub'),('EVIDENCE','evidence.pub')]:
    raw = (ROOT/name).read_bytes()
    assert sha(raw) == identities[role]['public_key_file_sha256']
    keys[role] = serialization.load_ssh_public_key(raw)
assert identities['TASK']['public_key_raw_sha256'] != identities['EVIDENCE']['public_key_raw_sha256']
def pair(mode):
    t,e = read(mode+'_TASK.json'),read(mode+'_EVIDENCE.json')
    for role,v in [('TASK',t),('EVIDENCE',e)]:
        signature = bytes.fromhex(v['signature']) if role=='TASK' else base64.b64decode(v['signature'], validate=True)
        keys[role].verify(signature,canon({k:x for k,x in v.items() if k!='signature'}))
    assert t['authority']=='GO-COMMAND-CENTER' and t['environment']=='HK-STAGING-01'
    for k in ['task_id','nonce','action_id','environment']: assert t[k]==e[k]
    for k in ['release_id','candidate_image_id','expected_current_image_id']: assert t['parameters'][k]==e[k]
    assert e['status']=='SUCCESS'
    assert t['issued_at'] <= e['started_at'] <= e['completed_at']
    return t,e
deploy,de = pair('DEPLOY'); verify,ve = pair('POST_VERIFY')
assert de['executor_result']=='DEPLOY_OK' and ve['executor_result']=='VERIFY_OK'
assert deploy['task_id'] != verify['task_id'] and deploy['nonce'] != verify['nonce']
assert de['completed_at'] < verify['issued_at'] <= ve['started_at'] <= ve['completed_at'] < verify['expires_at']
contract=read('CANDIDATE_CONTRACT.json');h=read('HK_HOST_READBACK.json');csha=sha((ROOT/'CANDIDATE_CONTRACT.json').read_bytes())
assert csha == '23d78ea846b21ace5318335eacb2a75826db5ff56cd925c8f8c58f6a83babed6'
image=contract['candidate']['image_id']
for t,e in [(deploy,de),(verify,ve)]:
    assert t['parameters']['candidate_contract_sha256']==e['candidate_contract_sha256']==csha
    assert t['parameters']['candidate_image_id']==image
assert verify['parameters']['expected_current_image_id']==image
for name in ['alembic_current','alembic_head','api_health','candidate_image','compose_baseline','env_baseline','expected_current_image','worker_process_liveness']: assert ve['gate_results'][name]=='PASS'
assert ve['gate_results']['application_health_proven'] is False
assert len(h['deploy_records'])==1
for item in [h['contract'],*h['deploy_records'],*h['migration_records']]:
    raw=base64.b64decode(item['raw_base64'],validate=True)
    assert sha(raw)==item['sha256'] and json.loads(raw)==item['content']
assert h['contract']['sha256']==csha
record=h['deploy_records'][0]['content']
assert h['deploy_records'][0]['sha256']==de['deploy_record_sha256']
assert record['record_id']==de['deploy_record_id'] and record['task_id']==deploy['task_id'] and record['nonce']==deploy['nonce']
assert record['candidate_contract_sha256']==csha and record['candidate_image_id']==image
assert record['task_canonical_sha256']==sha(canon({k:v for k,v in deploy.items() if k!='signature'}))
migration=next(x for x in h['migration_records'] if x['content']['schema']=='go.hk-forward-migration-receipt.v1')
assert migration['sha256']==de['gate_results']['migration_record_sha256']
assert migration['content']['result']['prestate']=='0133_flight_change_plan'
assert migration['content']['result']['poststate']=='0137_hosted_unknown_episode'
assert migration['content']['contract_sha256']==csha
assert migration['content']['task_binding']['canonical_sha256']==record['task_canonical_sha256']
assert not h['pending_migration_intent']
window=de['execution_window'];unsigned={k:v for k,v in deploy.items() if k!='signature'}
assert window['task_sha256']==sha(canon(deploy))
assert window['started_at']==de['started_at'] and window['completed_at']==de['completed_at']
assert window['claimed_at'] < deploy['expires_at'] and 0<=window['elapsed_milliseconds']<=900000
containers={x['service']:x for x in h['containers']}
services={x['service'] for x in record['targets']}
assert len(services)==record['target_count']==8
for service in services:
    x=containers[service];assert x['running'] and x['image']==image and x['restart_count']==0
    assert x['working_dir']=='/workspace'
    assert x['isolation_flags']['MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED']=='false'
    assert x['isolation_flags']['TRAVEL_INTELLIGENCE_ENABLED']=='false'
assert containers['api']['health']=='healthy'
for previous in record['protected_non_target_inventory']:
    current=containers[previous['service']]
    assert current['id']==previous['container_id'] and current['image']==previous['image_id']
for task in [deploy,verify]:
    attempts=[x for x in h['attempts'] if x['task_id']==task['task_id']]
    completed=[x for x in h['processed'] if x['task_id']==task['task_id']]
    assert len(attempts)==1 and attempts[0]['attempt_number']==1
    assert len(completed)==1 and completed[0]['status']=='completed'
out={'schema':'go.issue103.deployment-closeout.v1','status':'PASS_SCOPED','scope':'HK-STAGING_DEPLOY_AND_INDEPENDENT_VERIFY',
     'source_sha':contract['candidate']['source_commit'],'image_id':image,'application_tree':contract['candidate']['application_git_tree'],
     'candidate_contract_sha256':csha,'deployment_complete':True,'deploy_task':deploy['task_id'],'deploy_completed_at':de['completed_at'],
     'post_verify_task':verify['task_id'],'post_verify_completed_at':ve['completed_at'],'host_observed_at':h['observed_at'],
     'database_revision':'0137_hosted_unknown_episode','signatures':'PASS','record_hashes':'PASS','fixed_eight_services':'PASS',
     'non_targets_unchanged':'PASS','single_attempt':'PASS','application_health_proven':False,
     'final_release':'HOLD','production':'HOLD','real_supplier_connections':'HOLD'}
(ROOT/'DEPLOYMENT_CLOSEOUT.json').write_text(json.dumps(out,sort_keys=True,indent=2)+'\n')
print(json.dumps(out,sort_keys=True))
