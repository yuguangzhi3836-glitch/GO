"""Fixed-host, fixed-record read-only acceptance. No configuration contents or keys."""
import base64,datetime,hashlib,json,os,re,socket,stat,subprocess
from pathlib import Path
assert socket.gethostname()=='iZj6ccs8t04f1p4d8pe69zZ'
TASK='go-boss-deploy-74080bacd5d4fac2c14a9406'
VERIFY='go-boss-post-deploy-verify-4c1b9fcb54e9'
CONTRACT='36622f0648051d57d5918ea4ff7b9ac4e74f9c686e8f2c503f66bda15bd4b120'
IMAGE='sha256:633a22a0766e587587eeb324ebb6db78dee321118f996b58803da0d7ac34cbf0'
RECORD='5bc1e728983978aad50fe22deb65db4568525d94a318ed109b57c81bcdc048b9'
RECORD_SHA='bd1f4b0e658b9ab34f7aa4e8737b918d4fddd9cd8da9f98478b528a2a410dbbc'
SERVICES={'api','recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker'}
def run(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=45).stdout

def fixed_file(path):
 for a in path.parents:
  s=a.lstat();assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022
 s=path.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:return f.read()

out={'schema':'go.pr196.readonly-host-acceptance.v1','hostname':socket.gethostname(),'task_id':TASK,'post_verify_task_id':VERIFY}
ids=run(['/usr/bin/docker','ps','-q','--filter','label=com.docker.compose.project=go-822-staging']).split();assert ids
items=json.loads(run(['/usr/bin/docker','inspect',*ids]));out['containers']=[];api=None
for d in items:
 c=d['Config'];s=d['State'];service=c.get('Labels',{}).get('com.docker.compose.service')
 if service not in SERVICES:continue
 allowed={'MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED','TRAVEL_INTELLIGENCE_ENABLED','PYTHONPATH'}
 flags={k:v for entry in c.get('Env',[]) for k,_,v in [entry.partition('=')] if k in allowed}
 row={'service':service,'id':d['Id'],'image':d['Image'],'running':s['Running'],'status':s['Status'],'health':s.get('Health',{}).get('Status'),'restart_count':d['RestartCount'],'working_dir':c.get('WorkingDir'),'isolation_flags':flags}
 assert row['image']==IMAGE and row['running'] and row['status']=='running' and row['restart_count']==0 and row['working_dir']=='/workspace'
 assert flags.get('MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED')=='false' and flags.get('TRAVEL_INTELLIGENCE_ENABLED')=='false'
 if service=='api':assert row['health']=='healthy';api=d['Id']
 out['containers'].append(row)
assert len(out['containers'])==8 and {x['service'] for x in out['containers']}==SERVICES and api
path=Path('/etc/go-hk-deployctl/candidate-contracts-v1')/(CONTRACT+'.json');raw=fixed_file(path);assert hashlib.sha256(raw).hexdigest()==CONTRACT
out['contract']={'path':str(path),'sha256':CONTRACT,'content_exported':False}
path=Path('/var/lib/go-hk-deployctl/deploy-records')/(RECORD+'.json');raw=fixed_file(path);assert hashlib.sha256(raw).hexdigest()==RECORD_SHA
record=json.loads(raw);assert record['task_id']==TASK and record['record_id']==RECORD
out['deploy_records']=[{'path':str(path),'sha256':RECORD_SHA,'raw_base64':base64.b64encode(raw).decode(),'content':record}]
pending=Path('/var/lib/go-hk-deployctl/migrations-v1/pending.json');out['pending_migration_intent']=pending.exists() or pending.is_symlink();assert not out['pending_migration_intent']
# Same read-only current/heads commands used by the reviewed VERIFY collector.
base=['/usr/bin/docker','exec','-e','PYTHONDONTWRITEBYTECODE=1','-w','/workspace',api,'/usr/local/bin/alembic']
current=re.findall(r'(?m)^Rev:\s+([A-Za-z0-9_]+)(?:\s|$)',run(base+['current','-v']))
head=re.findall(r'(?m)^([A-Za-z0-9_]+)\s+\(head\)\s*$',run(base+['heads']))
assert current==head==['0137_hosted_unknown_episode']
out['database']={'current_revision':current[0],'head_revision':head[0],'read_only_commands':['alembic current -v','alembic heads'],'raw_command_output_exported':False}
out['agent_timer']=run(['systemctl','is-active','go-hk-agent.timer']).strip();assert out['agent_timer']=='active'
out['observed_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();out['control_plane_changed']=False
print(json.dumps(out,sort_keys=True,separators=(',',':')))
