"""Fixed isolated candidate-image CANARY runtime; no caller controlled Docker argv."""
import hashlib, json, os, pathlib, re, secrets, subprocess

IMAGE=re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256=re.compile(r"^[0-9a-f]{64}$")
RELEASE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
COMPOSE='/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml'
ENV='/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env'
COMPOSE_SHA='7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895'
ENV_SHA='6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc'
PROJECT='go-822-staging'
SERVICES=('api','recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker')
HEAD='0114_ext_truth_incident_hard'
HEAD_LINE=re.compile(r'^([0-9][0-9a-z_]*) \(head\)\n?$')

class Reject(ValueError): pass
class ProductionRunner:
 def run(self,argv,timeout):
  return subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout,check=False,shell=False)

def _sha(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def production_inputs(runner, expected):
 targets=[]
 for service in SERVICES:
  ps=runner.run(['/usr/bin/docker','ps','-aq','--filter',f'label=com.docker.compose.project={PROJECT}','--filter',f'label=com.docker.compose.service={service}'],20)
  ids=[x for x in ps.stdout.splitlines() if x]
  if ps.returncode or len(ids)!=1: raise Reject('E_EXPECTED_CURRENT_IMAGE_MISMATCH')
  ins=runner.run(['/usr/bin/docker','inspect',ids[0]],20)
  if ins.returncode: raise Reject('E_EXPECTED_CURRENT_IMAGE_MISMATCH')
  targets.append(json.loads(ins.stdout)[0].get('Image'))
 return {'compose_sha':_sha(COMPOSE),'env_sha':_sha(ENV),'target_images':tuple(targets),'expected':expected}

def _baseline(inputs, expected):
 if inputs.get('compose_sha')!=COMPOSE_SHA or inputs.get('env_sha')!=ENV_SHA: raise Reject('E_BASELINE_DRIFT')
 if inputs.get('expected')!=expected or tuple(inputs.get('target_images',()))!=(expected,)*8: raise Reject('E_EXPECTED_CURRENT_IMAGE_MISMATCH')

def _name(): return 'go-hk-canary-'+secrets.token_hex(12)
def _isolated_args(name,image,entry,tail):
 return ['/usr/bin/docker','run','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','256m','--cpus','0.50','--tmpfs','/tmp:rw,nosuid,nodev,size=64m','--workdir','/app','--env','HOME=/tmp','--env','PYTHONPYCACHEPREFIX=/tmp/pycache','--entrypoint',entry,image,*tail]

def _one(runner, name, image, entry, tail, timeout):
 try:
  result=runner.run(_isolated_args(name,image,entry,tail),timeout)
  if result.returncode: raise Reject('E_CANARY_COMPILE_FAILED' if entry.endswith('python') else 'E_CANARY_ALEMBIC_HEAD_MISMATCH')
  return result.stdout
 except subprocess.TimeoutExpired as exc: raise Reject('E_CANARY_TIMEOUT') from exc
 finally:
  cleanup=runner.run(['/usr/bin/docker','rm','-f',name],20)
  if cleanup.returncode: raise Reject('E_CANARY_CLEANUP_FAILED')

def parse_alembic_head(raw):
 """Accept exactly one canonical Alembic ``heads`` line and one expected head."""
 if not isinstance(raw,str): raise Reject('E_CANARY_ALEMBIC_HEAD_MISMATCH')
 match=HEAD_LINE.fullmatch(raw)
 if match is None or match.group(1)!=HEAD: raise Reject('E_CANARY_ALEMBIC_HEAD_MISMATCH')
 return match.group(1)

def run_canary(release,candidate,package,expected,runner=None,inputs=None,artifact=None):
 if not isinstance(release,str) or not RELEASE.fullmatch(release): raise Reject('E_RELEASE_ID')
 if not isinstance(candidate,str) or not IMAGE.fullmatch(candidate): raise Reject('E_CANDIDATE_IMAGE_MISSING')
 if not isinstance(package,str) or not SHA256.fullmatch(package): raise Reject('E_CANDIDATE_PACKAGE_INVALID')
 if not isinstance(expected,str) or not IMAGE.fullmatch(expected): raise Reject('E_EXPECTED_CURRENT_IMAGE_MISMATCH')
 runner=runner or ProductionRunner(); inputs=inputs or production_inputs(runner,expected)
 _baseline(inputs,expected)
 # The candidate is the sealed package, resolved into Docker here.  There is no
 # registry digest to compare: a manifest digest is not an image config ID, and a
 # host-built image that was never pushed has no digest at all.
 artifact.materialise(runner,package,candidate)
 inspected=runner.run(['/usr/bin/docker','image','inspect',candidate,'--format','{{.Id}}'],20)
 if inspected.returncode: raise Reject('E_CANDIDATE_IMAGE_MISSING')
 if inspected.stdout.strip()!=candidate: raise Reject('E_CANDIDATE_IMAGE_ID_MISMATCH')
 compile_out=_one(runner,_name(),candidate,'/usr/local/bin/python',['-m','compileall','-q','/app'],90)
 alembic_out=_one(runner,_name(),candidate,'/usr/local/bin/alembic',['heads'],45)
 parse_alembic_head(alembic_out)
 return {'compose_baseline':'PASS','env_baseline':'PASS','expected_current_image':'PASS','candidate_image':'PASS','python_compile':'PASS','alembic_head':'PASS','container_isolation':'PASS','container_cleanup':'PASS','application_boot_proven':False,'application_health_proven':False,'database_connectivity_proven':False}
