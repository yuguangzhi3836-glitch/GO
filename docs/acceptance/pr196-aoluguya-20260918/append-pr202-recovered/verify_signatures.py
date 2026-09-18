"""Verify recovered original signed objects; performs no remote operation."""
import base64,datetime,hashlib,json
from pathlib import Path
from cryptography.hazmat.primitives import serialization
P=Path(__file__).resolve().parent
canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
stamp=lambda s:datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
keys={}
for role,pin in [('task','7329ad0eff6c38973b0aa5c7481ae9e61d8383dd98f790940c8970eceaaad42c'),('evidence','3800e9a87b2fe47c2ccdb18209ac35bec0cfe5cc7a1c1ad3927573fe848d7ae3')]:
 raw=(P/(role+'.pub')).read_bytes();assert hashlib.sha256(raw).hexdigest()==pin
 keys[role]=serialization.load_ssh_public_key(raw)
result={}
candidate='a2981291144ca394f4fee42a5d6b52e47d9dbcf1c6ef3fea956283ce8be860d7'
image='sha256:3652b1d6392ee8eed816bfa484872bfc443a95abbd36bcbca887c96975915cdf'
for stage in ('TEST','CANARY','VERIFY','DEPLOY','POST_VERIFY'):
 t,e=[json.loads((P/(stage+'_'+kind+'.json')).read_bytes()) for kind in ('TASK','EVIDENCE')]
 for role,obj in [('task',t),('evidence',e)]:
  sig=bytes.fromhex(obj['signature']) if role=='task' else base64.b64decode(obj['signature'],validate=True)
  keys[role].verify(sig,canonical({k:v for k,v in obj.items() if k!='signature'}))
 assert all(t[k]==e[k] for k in ('task_id','nonce','action_id','environment'))
 assert t['environment']=='HK-STAGING-01' and t['authority']=='GO-COMMAND-CENTER' and e['status']=='SUCCESS'
 if stage in ('CANARY','DEPLOY','POST_VERIFY'):
  assert t['parameters']['candidate_contract_sha256']==e['candidate_contract_sha256']==candidate
  assert t['parameters']['candidate_image_id']==e['candidate_image_id']==image
 if stage=='DEPLOY':
  w=e['execution_window'];assert w['budget_seconds']==900 and 0<w['elapsed_milliseconds']<=900000
  assert stamp(t['issued_at'])<=stamp(w['claimed_at'])==stamp(e['started_at'])<stamp(t['expires_at'])
  assert stamp(e['completed_at'])-stamp(e['started_at'])<=datetime.timedelta(seconds=900)
  # Installed execution_window binds the complete signed Task, including signature.
  assert w['task_sha256']==hashlib.sha256(canonical(t)).hexdigest()
  assert e['executor_result']=='DEPLOY_OK'
  assert e['deploy_record_id']=='433aa1fcee0963be6dfc8e79a05ca1868da575f25555548fde4729a86cd0c1f1'
  assert e['deploy_record_sha256']=='22c9712581e7dc175475442b64bf03cd8c7efe59afbf4c20dd7073474f9c0016'
 else:assert stamp(t['issued_at'])<=stamp(e['started_at'])<=stamp(e['completed_at'])<=stamp(t['expires_at'])
 result[stage]={'status':'PASS','task_id':t['task_id'],'executor_result':e['executor_result'],'completed_at':e['completed_at']}
result={'status':'PASS','scope':'Recovered original signatures, Task/Evidence identity, candidate and execution window; no fresh host or media observation','stages':result}
(P/'SIGNATURE_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
