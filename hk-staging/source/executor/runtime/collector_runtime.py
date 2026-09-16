from dataclasses import dataclass
import hashlib, json, os, re, subprocess, time
WORKER_LIVENESS_OBSERVATION_SECONDS=60
@dataclass(frozen=True)
class ProcessResult:
 argv: tuple; returncode: int; stdout: str; stderr: str
class ProductionRunner:
 def run(self,argv):
  # This is executor-owned configuration, not a Task input.  Only the fixed
  # Docker Compose invocation receives the interpolation variable required by
  # the frozen R3.1.5 Compose file; all inherited environment remains intact.
  env=os.environ.copy()
  if tuple(argv[:2])==(DOCKER,'compose'):
   env['GO_RUNTIME_ENV_FILE']=ENV_FILE
  p=subprocess.run(argv,shell=False,capture_output=True,text=True,check=False,env=env)
  return ProcessResult(tuple(argv),p.returncode,p.stdout,p.stderr)
class FakeRunner:
 def __init__(self,fixtures): self.fixtures={tuple(k):v for k,v in fixtures.items()};self.calls=[]
 def run(self,argv):
  k=tuple(argv);self.calls.append(k)
  if k not in self.fixtures: raise ValueError('unknown argv')
  value=self.fixtures[k]
  if isinstance(value,list):
   if not value: raise ValueError('fixture exhausted')
   return value.pop(0)
  return value
def sha256_file(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(65536),b''):h.update(b)
 return h.hexdigest()
def observe(sleeper=time.sleep): sleeper(WORKER_LIVENESS_OBSERVATION_SECONDS)
DOCKER='/usr/bin/docker'
COMPOSE_PROJECT='go-822-staging'
PROJECT=COMPOSE_PROJECT
COMPOSE_FILE='/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml'
COMPOSE_SHA256='7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895'
ENV_FILE='/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env'
ENV_SHA256='6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc'
API_SERVICE='api'
ALEMBIC_WORKDIR='/app'; ALEMBIC_EXECUTABLE='/usr/local/bin/alembic'
EXPECTED_REVISION='0133_flight_change_plan'
def collect_api(runner, expected):
 p=[DOCKER,'ps','-aq','--filter',f'label=com.docker.compose.project={PROJECT}','--filter',f'label=com.docker.compose.service={API_SERVICE}'];x=runner.run(p)
 if x.returncode or len(x.stdout.splitlines())!=1: raise ValueError('api selection')
 i=[DOCKER,'inspect',x.stdout.strip()];y=runner.run(i)
 if y.returncode: raise ValueError('inspect')
 import json
 try:d=json.loads(y.stdout)[0];s=d['State'];h=s['Health']['Status']
 except Exception:raise ValueError('inspect parse')
 if d['Image']!=expected or not s['Running'] or s['Status']!='running' or h!='healthy':raise ValueError('api gate')
 return d
WORKERS=('recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker')
def workers(runner, expected, sleeper=time.sleep):
 def snap():
  out=[]
  for w in WORKERS:
   p=[DOCKER,'ps','-aq','--filter',f'label=com.docker.compose.project={PROJECT}','--filter',f'label=com.docker.compose.service={w}'];x=runner.run(p)
   if x.returncode or len(x.stdout.splitlines())!=1:raise ValueError('worker')
   i=[DOCKER,'inspect',x.stdout.strip()];y=runner.run(i)
   import json
   try:d=json.loads(y.stdout)[0];s=d['State']
   except Exception:raise ValueError('inspect')
   if d['Image']!=expected or not s['Running'] or s['Status']!='running' or s['Restarting'] or s['OOMKilled']:raise ValueError('state')
   out.append((d['Id'],d['Image'],s['StartedAt'],d['RestartCount']))
  return out
 a=snap();sleeper(60);b=snap()
 if a!=b:raise ValueError('drift')
 return {'process_liveness_pass':7,'application_health_proven':False}

def _parse_current_revision(stdout):
 matches=re.findall(r'(?m)^Rev:\s+([A-Za-z0-9_]+)(?:\s|$)',stdout)
 if len(matches)!=1:raise ValueError('current parse')
 return matches[0]

def _parse_head_revision(stdout):
 matches=re.findall(r'(?m)^([A-Za-z0-9_]+)\s+\(head\)\s*$',stdout)
 if len(matches)!=1:raise ValueError('head parse')
 return matches[0]

def collect_api_alembic(runner, expected_image, expected_revision=EXPECTED_REVISION):
 api=collect_api(runner,expected_image)
 return _collect_alembic_for_api(runner,api,expected_revision)

def _collect_alembic_for_api(runner, api, expected_revision=EXPECTED_REVISION):
 api_id=api.get('Id')
 if not isinstance(api_id,str) or not api_id:raise ValueError('api id')
 current=[DOCKER,'exec','-w',ALEMBIC_WORKDIR,api_id,ALEMBIC_EXECUTABLE,'current','-v']
 current_result=runner.run(current)
 if current_result.returncode:raise ValueError('current exit')
 current_revision=_parse_current_revision(current_result.stdout)
 heads=[DOCKER,'exec','-w',ALEMBIC_WORKDIR,api_id,ALEMBIC_EXECUTABLE,'heads']
 heads_result=runner.run(heads)
 if heads_result.returncode:raise ValueError('heads exit')
 head_revision=_parse_head_revision(heads_result.stdout)
 if current_revision!=expected_revision or head_revision!=expected_revision or current_revision!=head_revision:raise ValueError('revision drift')
 return {'current_revision':current_revision,'head_revision':head_revision,'api_id':api_id}

@dataclass(frozen=True)
class _VerifyInputs:
 compose_path: str
 compose_sha256: str
 env_path: str
 env_sha256: str

_PRODUCTION_VERIFY_INPUTS=_VerifyInputs(COMPOSE_FILE,COMPOSE_SHA256,ENV_FILE,ENV_SHA256)

def _collect_verify(runner, candidate_image_id, expected_current_image_id, inputs, sleeper=time.sleep):
 if candidate_image_id!=expected_current_image_id:raise ValueError('candidate image')
 if sha256_file(inputs.compose_path)!=inputs.compose_sha256:raise ValueError('compose baseline')
 if sha256_file(inputs.env_path)!=inputs.env_sha256:raise ValueError('env baseline')
 api=collect_api(runner,expected_current_image_id)
 worker_result=workers(runner,expected_current_image_id,sleeper)
 alembic_result=_collect_alembic_for_api(runner,api)
 return {
  'target_service_count':1+len(WORKERS),
  'all_target_services_same_image':True,
  'api_docker_health':'healthy',
  'worker_process_liveness_pass_count':worker_result['process_liveness_pass'],
  'application_health_proven_count':0,
  'alembic_current_equals_head':alembic_result['current_revision']==alembic_result['head_revision'],
  'health_semantic_overclaim':False,
 }

def collect_verify(runner, candidate_image_id, expected_current_image_id, sleeper=time.sleep):
 return _collect_verify(runner,candidate_image_id,expected_current_image_id,_PRODUCTION_VERIFY_INPUTS,sleeper)
