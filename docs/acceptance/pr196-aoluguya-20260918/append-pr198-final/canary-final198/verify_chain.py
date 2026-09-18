"""Offline original-signed PR198 chain checks. Missing pairs are WAIT, never PASS."""
import base64,datetime,hashlib,importlib.util,json
from pathlib import Path
from cryptography.hazmat.primitives import serialization
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
CANDIDATE_CONTRACT='d0a4d82a1e56e7ff96ddedc1668534f57961aab6875ca9c0f7997d37e72b56fb'
CURRENT_CONTRACT='36622f0648051d57d5918ea4ff7b9ac4e74f9c686e8f2c503f66bda15bd4b120'
CANDIDATE_IMAGE='sha256:28c8b3b34992d9d4aefb4a58d892507ef06c063d955b2da86fe0e3560013d3fe'
CURRENT_IMAGE='sha256:633a22a0766e587587eeb324ebb6db78dee321118f996b58803da0d7ac34cbf0'
PUBLIC_PINS={'TASK':'7329ad0eff6c38973b0aa5c7481ae9e61d8383dd98f790940c8970eceaaad42c','EVIDENCE':'3800e9a87b2fe47c2ccdb18209ac35bec0cfe5cc7a1c1ad3927573fe848d7ae3'}
STAGES={
 'CANARY':('HK_STAGING_CANARY',CANDIDATE_CONTRACT,CANDIDATE_IMAGE,CURRENT_IMAGE,'CANARY_OK'),
 'VERIFY':('HK_STAGING_VERIFY',CURRENT_CONTRACT,CURRENT_IMAGE,CURRENT_IMAGE,'VERIFY_OK'),
 'DEPLOY':('HK_STAGING_DEPLOY',CANDIDATE_CONTRACT,CANDIDATE_IMAGE,CURRENT_IMAGE,'DEPLOY_OK'),
 'POST_VERIFY':('HK_STAGING_VERIFY',CANDIDATE_CONTRACT,CANDIDATE_IMAGE,CANDIDATE_IMAGE,'VERIFY_OK')}
VERIFY_GATES=('alembic_current','alembic_head','api_health','candidate_image','compose_baseline','env_baseline','expected_current_image','worker_process_liveness')
GATES={
 'CANARY':('alembic_head','candidate_image','compose_baseline','container_cleanup','container_isolation','env_baseline','expected_current_image','python_compile'),
 'VERIFY':VERIFY_GATES,'POST_VERIFY':VERIFY_GATES,
 'DEPLOY':('candidate_binding','current_state','durable_previous_state','fixed_scope','migration_source_bound','no_migration','post_deploy_verify','rds_poststate_match','rds_prestate_match')}
canon=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
sha=lambda v:hashlib.sha256(v).hexdigest()

def no_duplicates(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate_json_key')
  d[k]=v
 return d

def read(path):return json.loads(path.read_text(),object_pairs_hook=no_duplicates)

def window_module():
 path=ROOT/'integration-gate/pr195-admission/execution_window.py'
 if sha(path.read_bytes())!='8b4213eea8ea29b838490d41b99070fc5726d8207812be10be872ab149f6ff3e':raise ValueError('execution_window_source_pin')
 spec=importlib.util.spec_from_file_location('reviewed_execution_window',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def contracts():
 result={}
 for identity,path,image in [(CANDIDATE_CONTRACT,ROOT/'integration-gate/contacts-next/CANDIDATE_CONTRACT.json',CANDIDATE_IMAGE),(CURRENT_CONTRACT,ROOT/'integration-gate/pr195-admission/CANDIDATE_CONTRACT.json',CURRENT_IMAGE)]:
  c=read(path)
  if sha(canon(c))!=identity or c['candidate']['image_id']!=image:raise ValueError('immutable_contract_identity')
  if c['schema']!='go.hk-candidate-contract.v2' or c['migration_required'] is not False or c['baseline_revision']!=c['target_revision'] or c['migration_source_digest']!=c['baseline_migration_source_digest']:raise ValueError('immutable_same_revision_contract')
  result[identity]=c
 return result

def signatures(task,evidence):
 for role,value,name in [('TASK',task,'task.pub'),('EVIDENCE',evidence,'evidence.pub')]:
  key=(ROOT/'closeout'/name).read_bytes()
  if sha(key)!=PUBLIC_PINS[role]:raise ValueError('public_key_pin')
  sig=bytes.fromhex(value['signature']) if role=='TASK' else base64.b64decode(value['signature'],validate=True)
  serialization.load_ssh_public_key(key).verify(sig,canon({k:v for k,v in value.items() if k!='signature'}))

def bindings(stage,task,evidence,known_contracts):
 action,identity,image,current,result=STAGES[stage]
 for key in ('task_id','nonce','action_id','environment'):
  if task[key]!=evidence[key]:raise ValueError('task_evidence_binding:'+key)
 if task['action_id']!=action or task['environment']!='HK-STAGING-01' or task['authority']!='GO-COMMAND-CENTER' or evidence['status']!='SUCCESS':raise ValueError('signed_scope')
 if evidence['executor_result']!=result:raise ValueError('executor_result')
 parameters=task['parameters']
 for key,value in [('candidate_contract_sha256',identity),('candidate_image_id',image),('expected_current_image_id',current)]:
  if parameters.get(key)!=value or evidence.get(key)!=value:raise ValueError('stage_binding:'+key)
 if parameters.get('release_id')!=evidence.get('release_id') or not parameters.get('release_id'):raise ValueError('release_binding')
 # Ordinary VERIFY Evidence does not carry a package. Bind package where Task defines it.
 package=parameters.get('candidate_package_sha256')
 if stage in ('CANARY','DEPLOY') and package is None:raise ValueError('task_package_missing')
 if package is not None and package!=known_contracts[identity]['candidate']['package_sha256']:raise ValueError('task_package_contract_binding')
 if 'task_canonical_sha256' in evidence and evidence['task_canonical_sha256']!=sha(canon({k:v for k,v in task.items() if k!='signature'})):raise ValueError('task_canonical_binding')
 for gate in GATES[stage]:
  if evidence.get('gate_results',{}).get(gate)!='PASS':raise ValueError('required_gate:'+gate)


def verify_pair(stage,task,evidence,known_contracts):
 signatures(task,evidence);bindings(stage,task,evidence,known_contracts)
 window=window_module()
 if stage=='DEPLOY':window.validate(task,evidence)
 elif not window.stamp(task['issued_at'])<=window.stamp(evidence['started_at'])<=window.stamp(evidence['completed_at'])<=window.stamp(task['expires_at']):raise ValueError('task_evidence_timeline')
 return {'status':'PASS','task_id':task['task_id'],'started_at':evidence['started_at'],'completed_at':evidence['completed_at'],'contract_sha256':STAGES[stage][1],'package_binding_source':'Task + immutable contract' if 'candidate_package_sha256' in task['parameters'] else 'Not a field of this VERIFY Task; image + contract validated'}

def deployment_canary_link(deploy_task,canary_task):
 if deploy_task['parameters'].get('canary_evidence_id')!=canary_task['parameters'].get('release_id') or not canary_task['parameters'].get('release_id'):raise ValueError('deploy_canary_reference_mismatch')

def verify_chain(directory=HERE):
 directory=Path(directory);known=contracts();results={};pairs={}
 for stage in STAGES:
  paths=[directory/(stage+'_'+kind+'.json') for kind in ('TASK','EVIDENCE')]
  missing=[p.name for p in paths if not p.is_file()]
  if missing:
   results[stage]={'status':'WAIT','missing_files':missing};continue
  try:
   task,evidence=[read(p) for p in paths];results[stage]=verify_pair(stage,task,evidence,known)
   results[stage]['original_file_sha256']={p.name:sha(p.read_bytes()) for p in paths};pairs[stage]=(task,evidence)
  except Exception as exc:results[stage]={'status':'FAIL','error_type':type(exc).__name__,'reason':str(exc) if isinstance(exc,ValueError) else 'signature_or_input_rejected'}
 # Ordering is a relation of actual successful pairs; missing links never gain PASS.
 if 'DEPLOY' in pairs:
  if 'CANARY' in pairs:
   try:deployment_canary_link(pairs['DEPLOY'][0],pairs['CANARY'][0])
   except ValueError as exc:results['DEPLOY']={'status':'FAIL','reason':str(exc)}
  start=window_module().stamp(pairs['DEPLOY'][1]['started_at'])
  for earlier in ('CANARY','VERIFY'):
   if earlier in pairs and window_module().stamp(pairs[earlier][1]['completed_at'])>start:results['DEPLOY']={'status':'FAIL','reason':earlier+'_completed_after_deploy_start'}
 if 'POST_VERIFY' in pairs and 'DEPLOY' in pairs:
  if window_module().stamp(pairs['POST_VERIFY'][1]['started_at'])<window_module().stamp(pairs['DEPLOY'][1]['completed_at']):results['POST_VERIFY']={'status':'FAIL','reason':'post_verify_precedes_deploy_completion'}
 statuses={r['status'] for r in results.values()}
 return {'schema':'go.pr198.formal-chain-offline-review.v1','status':'FAIL' if 'FAIL' in statuses else 'WAIT' if 'WAIT' in statuses else 'PASS','stages':results,'candidate_contract_sha256':CANDIDATE_CONTRACT,'current_baseline_contract_sha256':CURRENT_CONTRACT,'candidate_image_id':CANDIDATE_IMAGE,'current_image_id':CURRENT_IMAGE,'remote_operations_performed':False,'scope':'Original signed Task/Evidence, immutable identity, gates and execution timeline; no fresh host read or broader application-health claim'}

if __name__=='__main__':
 result=verify_chain();(HERE/'CHAIN_VERIFICATION.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps(result,sort_keys=True));raise SystemExit(1 if result['status']=='FAIL' else 0)
