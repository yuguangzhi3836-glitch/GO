"""Offline exact signed chain and supplied host snapshot binding."""
import base64, hashlib, json
from pathlib import Path
import verify_chain as chain
P=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
read=lambda n:json.loads((P/n).read_text())
def main():
 import subprocess,sys
 subprocess.run([sys.executable,str(P/'verify_chain.py')],check=True,capture_output=True)
 c=read('CHAIN_VERIFICATION.json');assert c['status']=='PASS'
 raw=(P/'HK_HOST_READBACK.json').read_bytes();assert sha(raw)=='f8d668601053a2abb959f8bc7a83f371d625cf6dc5ae422befc88d34f8e3bea1'
 h=json.loads(raw);d=read('DEPLOY_EVIDENCE.json');t=read('DEPLOY_TASK.json');pv=read('POST_VERIFY_EVIDENCE.json')
 assert h['hostname']=='iZj6ccs8t04f1p4d8pe69zZ' and h['task_id']==d['task_id'] and h['post_verify_task_id']==pv['task_id']
 assert h['control_plane_changed'] is False and h['pending_migration_intent'] is False and h['agent_timer']=='active'
 assert h['contract']['sha256']==chain.CANDIDATE_CONTRACT and h['contract']['content_exported'] is False
 services={'api','recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker'}
 assert len(h['containers'])==8 and {r['service'] for r in h['containers']}==services
 for r in h['containers']:
  assert r['image']==chain.CANDIDATE_IMAGE and r['running'] is True and r['status']=='running' and r['restart_count']==0 and r['working_dir']=='/workspace'
  assert all(r['isolation_flags'][k]=='false' for k in ['MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED','TRAVEL_INTELLIGENCE_ENABLED'])
  if r['service']=='api':assert r['health']=='healthy'
 assert h['database']['current_revision']==h['database']['head_revision']=='0137_hosted_unknown_episode'
 assert len(h['deploy_records'])==1
 rr=h['deploy_records'][0];rb=base64.b64decode(rr['raw_base64'],validate=True);r=json.loads(rb)
 assert r==rr['content'] and sha(rb)==rr['sha256']==d['deploy_record_sha256'] and r['record_id']==d['deploy_record_id']
 for k in ['task_id','nonce','action_id','environment']:assert r[k]==t[k]==d[k]
 for k in ['candidate_image_id','candidate_contract_sha256','candidate_package_sha256','expected_current_image_id','release_id']:assert r[k]==t['parameters'][k]
 assert r['migration_required'] is False and r['baseline_revision']==r['target_revision']=='0137_hosted_unknown_episode'
 assert r['task_canonical_sha256']==sha(chain.canon({k:v for k,v in t.items() if k!='signature'}))
 result={'schema':'go.pr198.formal-and-host-acceptance.v1','status':'PASS_SIGNED_CHAIN_AND_READONLY_HOST_BINDING','source_commit':'f827a3aefd95fd95dedb2bd2ecc93ae01111ea90','image_id':chain.CANDIDATE_IMAGE,'candidate_contract_sha256':chain.CANDIDATE_CONTRACT,'deploy_task_id':d['task_id'],'deploy_completed_at':d['completed_at'],'post_verify_task_id':pv['task_id'],'post_verify_completed_at':pv['completed_at'],'observed_at':h['observed_at'],'host_stdout_sha256':sha(raw),'deploy_record_sha256':sha(rb),'target_service_count':8,'all_same_image':True,'all_restart_count_zero':True,'api_health':'healthy','external_egress_enabled':False,'database_revision':h['database']['current_revision'],'database_head':h['database']['head_revision'],'migration_required':False,'control_plane_modified_by_readback':False,'application_health_proven':False,'limits':['Point-in-time runtime and signed deployment verification, not extended-load guarantee','Media persistence remains a separate unresolved product/storage issue; this report does not claim media persistence','No catalog/media mutations by this offline verifier']}
 (P/'VERIFICATION.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 names=[f'{s}_{kind}.json' for s in chain.STAGES for kind in ['TASK','EVIDENCE']]+['DEPLOY_REFERENCES.json','POST_VERIFY_REFERENCES.json','CHAIN_VERIFICATION.json','HK_HOST_READBACK.json','VERIFICATION.json','verify_chain.py','verify_host_closeout.py','host_readback.py','C13_BOUND_READONLY_REVIEW.json']
 assert all((P/n).is_file() for n in names)
 (P/'ARCHIVE_FILES.json').write_text(json.dumps({'scope':'PR198 signed deployment and host acceptance; media issue excluded','files':{n:sha((P/n).read_bytes()) for n in names}},sort_keys=True,indent=2)+'\n')
 print(result['status'])
if __name__=='__main__':main()
