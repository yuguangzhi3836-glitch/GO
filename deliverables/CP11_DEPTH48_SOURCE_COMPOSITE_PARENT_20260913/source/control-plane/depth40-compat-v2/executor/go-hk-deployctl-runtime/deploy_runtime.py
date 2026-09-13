"""Fixed, fail-closed HK-STAGING DEPLOY runtime.  No caller controls Docker argv."""
import hashlib,json,os,pathlib,re,secrets,tempfile,time

DOCKER='/usr/bin/docker'; PROJECT='go-822-staging'
COMPOSE='/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml'
ENV='/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env'
COMPOSE_SHA='7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895'
ENV_SHA='6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc'
RECORD_DIR='/var/lib/go-hk-deployctl/deploy-records'
SERVICES=('api','recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker')
IMAGE=re.compile(r'^sha256:[0-9a-f]{64}$'); DIGEST=re.compile(r'^[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}$')
TASK_ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'); NONCE=re.compile(r'^[A-Za-z0-9_-]{1,128}$'); SHA256=re.compile(r'^[0-9a-f]{64}$')
API_READINESS_ATTEMPTS=12
API_READINESS_INTERVAL_SECONDS=5

SITE=None
RECOVERY_GATE=None
class Reject(ValueError): pass
class DeployFailure(Reject):
    def __init__(self,code,record):
        self.record=record
        super().__init__(code)
def _sha(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def _run(runner,argv,timeout=120):
    # Reuse the frozen production collector runner interface: argv-only.
    # Timeout policy belongs to that fixed runner, not to a caller argument.
    out=runner.run(argv)
    # GNU timeout and the fixed production runner preserve 124 for a timeout.
    # Keep it distinct from an ordinary subprocess failure for fail-closed audit.
    if out.returncode==124: raise Reject('E_DEPLOY_TIMEOUT')
    if out.returncode: raise Reject('E_DEPLOY_SUBPROCESS_NONZERO')
    return out.stdout
def _ids(runner):
    found=[]
    for service in SERVICES:
        raw=_run(runner,[DOCKER,'ps','-q','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service='+service],20)
        ids=[x for x in raw.splitlines() if x]
        if len(ids)!=1: raise Reject('E_DEPLOY_TARGET_COUNT')
        found.append(ids[0])
    return found
def _inspect(runner,ids):
    raw=_run(runner,[DOCKER,'inspect',*ids],30)
    try: data=json.loads(raw)
    except Exception as exc: raise Reject('E_DEPLOY_INSPECT_PARSE') from exc
    if not isinstance(data,list) or len(data)!=8: raise Reject('E_DEPLOY_TARGET_COUNT')
    return data
def _validate_compose(runner,candidate):
    raw=_run(runner,[DOCKER,'compose','--env-file',ENV,'-p',PROJECT,'-f',COMPOSE,'config','--format','json'])
    try: config=json.loads(raw)
    except Exception as exc: raise Reject('E_COMPOSE_PARSE') from exc
    services=config.get('services',{})
    if set(services)!=set(SERVICES): raise Reject('E_COMPOSE_SCOPE')
    for name,item in services.items():
        if item.get('command')!=[name] or item.get('image')!=candidate: raise Reject('E_COMPOSE_ROLE_IMAGE')
        if item.get('cap_add') or item.get('entrypoint') or item.get('privileged') or item.get('network_mode') or item.get('pid') or item.get('build'): raise Reject('E_COMPOSE_UNSAFE_OVERRIDE')
        if item.get('pull_policy')!='never' or item.get('restart')!='no': raise Reject('E_COMPOSE_PULL_RESTART_POLICY')
        if item.get('read_only') is not True or item.get('user')!='10001:10001' or 'ALL' not in item.get('cap_drop',[]): raise Reject('E_COMPOSE_ISOLATION')
        if item.get('environment',{}).get('PYTHONPATH','/opt/go/source/src:/opt/go/site')!='/opt/go/source/src:/opt/go/site': raise Reject('E_COMPOSE_PYTHONPATH')
        mounts=item.get('volumes',[])
        if len(mounts)!=1 or mounts[0].get('type')!='volume' or mounts[0].get('target')!='/state': raise Reject('E_COMPOSE_MEDIA')
        source=mounts[0].get('source'); volume=config.get('volumes',{}).get(source,{})
        if volume.get('external') is not True or volume.get('name')!=SITE['media_volume']: raise Reject('E_COMPOSE_MEDIA')
    nets=config.get('networks',{})
    if len(nets)!=1 or any(v.get('external') is not True or v.get('name')!=SITE['network'] for v in nets.values()): raise Reject('E_COMPOSE_NETWORK')

def _precheck(runner,candidate,digest,expected):
    if SITE is None or candidate!=SITE['candidate']['image_id'] or expected!=SITE['previous']['image_id'] or digest!=SITE['candidate']['repo_digest']: raise Reject('E_UNBOUND_DEPLOYMENT')
    for profile in (SITE['candidate'],SITE['previous']):
        if _sha(profile['compose_path'])!=profile['compose_sha256'] or _sha(profile['env_path'])!=profile['env_sha256']: raise Reject('E_PROFILE_DRIFT')
    if RECOVERY_GATE is None: raise Reject('E_RECOVERY_PREPARATION_REQUIRED')
    RECOVERY_GATE.verify_plan(SITE)
    if not IMAGE.fullmatch(candidate): raise Reject('E_DEPLOY_CANDIDATE_IMAGE')
    if not IMAGE.fullmatch(expected): raise Reject('E_DEPLOY_EXPECTED_IMAGE')
    if not DIGEST.fullmatch(digest): raise Reject('E_DEPLOY_REPO_DIGEST')
    if _sha(COMPOSE)!=COMPOSE_SHA: raise Reject('E_DEPLOY_COMPOSE_DRIFT')
    if _sha(ENV)!=ENV_SHA: raise Reject('E_DEPLOY_ENV_DRIFT')
    image=_run(runner,[DOCKER,'image','inspect',candidate,'--format','{{.Id}}'],20).strip()
    if image!=candidate: raise Reject('E_DEPLOY_CANDIDATE_MISSING')
    digs=_run(runner,[DOCKER,'image','inspect',candidate,'--format','{{join .RepoDigests "\\n"}}'],20).splitlines()
    if digest not in digs: raise Reject('E_DEPLOY_REPO_DIGEST_BINDING')
    if _run(runner,[DOCKER,'image','inspect',digest,'--format','{{.Id}}'],20).strip()!=candidate: raise Reject('E_DEPLOY_REPO_DIGEST_BINDING')
    _validate_compose(runner,candidate)
    data=_inspect(runner,_ids(runner))
    if any(x.get('Image')!=expected for x in data): raise Reject('E_DEPLOY_CURRENT_IMAGE_DRIFT')
    return data
def _task_binding(binding):
    if not isinstance(binding,dict) or set(binding)!={'task_id','nonce','authority','canonical_sha256'}: raise Reject('E_DEPLOY_TASK_BINDING')
    if not TASK_ID.fullmatch(binding['task_id']) or not NONCE.fullmatch(binding['nonce']): raise Reject('E_DEPLOY_TASK_BINDING')
    if binding['authority']!='GO-COMMAND-CENTER' or not SHA256.fullmatch(binding['canonical_sha256']): raise Reject('E_DEPLOY_TASK_BINDING')
    return dict(binding)
def _repo_digest(runner,image):
    values=[v for v in _run(runner,[DOCKER,'image','inspect',image,'--format','{{join .RepoDigests "\\n"}}'],20).splitlines() if DIGEST.fullmatch(v)]
    return values[0] if len(values)==1 else None
def _non_target_snapshot(runner,target_ids):
    ids=sorted(v for v in _run(runner,[DOCKER,'ps','-aq'],20).splitlines() if v and v not in set(target_ids))
    return hashlib.sha256(('\\n'.join(ids)).encode()).hexdigest()
PROTECTED_NON_TARGET_SERVICES=('redis','caddy')
def _protected_non_target_inventory(runner):
    """Capture only the fixed protected services using stable Docker identity."""
    inventory=[]
    for service in PROTECTED_NON_TARGET_SERVICES:
        ids=[v for v in _run(runner,[DOCKER,'ps','-aq','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service='+service],20).splitlines() if v]
        if len(ids)!=1: raise Reject('E_DEPLOY_PROTECTED_NON_TARGET_BINDING')
        try: raw=json.loads(_run(runner,[DOCKER,'inspect',ids[0]],20))
        except Exception as exc: raise Reject('E_DEPLOY_PROTECTED_NON_TARGET_INSPECT') from exc
        if not isinstance(raw,list) or len(raw)!=1 or not isinstance(raw[0],dict): raise Reject('E_DEPLOY_PROTECTED_NON_TARGET_INSPECT')
        item=raw[0]; labels=item.get('Config',{}).get('Labels',{})
        image=item.get('Image'); cid=item.get('Id')
        if not isinstance(cid,str) or not IMAGE.fullmatch(image or '') or labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service: raise Reject('E_DEPLOY_PROTECTED_NON_TARGET_BINDING')
        networks=sorted((item.get('NetworkSettings',{}).get('Networks',{}) or {}).keys())
        inventory.append({'service':service,'container_id':cid,'container_name':str(item.get('Name','')).lstrip('/'),'image_id':image,'repo_digest':_repo_digest(runner,image),'compose_project':PROJECT,'compose_service':service,'networks':networks})
    return inventory
def _protected_non_target_snapshot(runner):
    inventory=_protected_non_target_inventory(runner)
    canonical=json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()
    return inventory,hashlib.sha256(canonical).hexdigest()
def _atomic_record(record):
    directory=pathlib.Path(RECORD_DIR)
    try: directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    except OSError as exc: raise Reject('E_DEPLOY_RECORD_PERSIST') from exc
    payload=json.dumps(record,sort_keys=True,separators=(',',':')).encode('utf-8')
    final=directory/(record['record_id']+'.json'); temp=directory/('.'+record['record_id']+'.'+secrets.token_hex(8)+'.tmp')
    try:
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as handle: handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.link(temp,final); os.unlink(temp); os.chmod(final,0o400)
        dirfd=os.open(directory,os.O_RDONLY); os.fsync(dirfd); os.close(dirfd)
    except FileExistsError as exc: raise Reject('E_DEPLOY_RECORD_COLLISION') from exc
    except OSError as exc:
        try: temp.unlink()
        except OSError: pass
        raise Reject('E_DEPLOY_RECORD_PERSIST') from exc
    return {'deploy_record_schema_version':'2','deploy_record_id':record['record_id'],'deploy_record_sha256':hashlib.sha256(payload).hexdigest(),'record_path':str(final)}
def _record_v2(release,candidate,digest,expected,data,runner,binding):
    binding=_task_binding(binding)
    targets=[]
    for service,container in zip(SERVICES,data):
        labels=container.get('Config',{}).get('Labels',{})
        image=container.get('Image')
        if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service or not isinstance(container.get('Id'),str) or not IMAGE.fullmatch(image or ''): raise Reject('E_DEPLOY_TARGET_BINDING')
        targets.append({'service':service,'container_id':container['Id'],'image_id':image,'repo_digest':_repo_digest(runner,image)})
    record_identity=hashlib.sha256(json.dumps({'task_id':binding['task_id'],'nonce':binding['nonce'],'release_id':release},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    protected_inventory,protected_hash=_protected_non_target_snapshot(runner)
    record={'deploy_record_schema_version':'2','record_id':record_identity,'created_at':int(time.time()),'environment':'HK-STAGING-01','action_id':'HK_STAGING_DEPLOY','task_id':binding['task_id'],'nonce':binding['nonce'],'authority':binding['authority'],'task_canonical_sha256':binding['canonical_sha256'],'release_id':release,'candidate_image_id':candidate,'candidate_repo_digest':digest,'expected_current_image_id':expected,'previous_runtime':dict(SITE['previous']),'candidate_runtime':dict(SITE['candidate']),'recovery_plan_sha256':SITE['recovery_plan']['sha256'],'compose_path':COMPOSE,'compose_sha256':COMPOSE_SHA,'runtime_env_path':ENV,'env_sha256':ENV_SHA,'target_count':8,'targets':targets,'non_target_container_inventory_sha256':_non_target_snapshot(runner,[x['container_id'] for x in targets]),'protected_non_target_inventory':protected_inventory,'protected_non_target_inventory_sha256':protected_hash}
    return _atomic_record(record)
def rollback_source_eligible(record,record_sha256,task,evidence):
    """Pure future-rollback source validator; it performs no Docker operation."""
    try:
        if not isinstance(record,dict) or record.get('deploy_record_schema_version')!='2' or not SHA256.fullmatch(record_sha256): return False
        if record.get('action_id')!='HK_STAGING_DEPLOY' or record.get('environment')!='HK-STAGING-01' or record.get('target_count')!=8 or len(record.get('targets',[]))!=8: return False
        if any(not IMAGE.fullmatch(x.get('image_id','')) for x in record['targets']): return False
        protected=record.get('protected_non_target_inventory')
        if not isinstance(protected,list) or [x.get('service') for x in protected]!=list(PROTECTED_NON_TARGET_SERVICES): return False
        canonical=json.dumps(protected,sort_keys=True,separators=(',',':')).encode()
        if record.get('protected_non_target_inventory_sha256')!=hashlib.sha256(canonical).hexdigest(): return False
        if not isinstance(task,dict) or not isinstance(evidence,dict): return False
        if task.get('action_id')!='HK_STAGING_DEPLOY' or evidence.get('action_id')!='HK_STAGING_DEPLOY' or evidence.get('status')!='SUCCESS': return False
        # The signed Task protocol deliberately keeps action inputs under
        # ``parameters``.  Do not accept a legacy/top-level release_id: that
        # would either reject real formal tasks or silently widen the schema.
        parameters=task.get('parameters')
        if not isinstance(parameters,dict): return False
        release_id=parameters.get('release_id')
        if not isinstance(release_id,str) or not release_id: return False
        for key in ('task_id','nonce'):
            if record.get(key)!=task.get(key) or evidence.get(key)!=task.get(key): return False
        if record.get('release_id')!=release_id or evidence.get('release_id')!=release_id: return False
        return evidence.get('deploy_record_schema_version')=='2' and evidence.get('deploy_record_id')==record.get('record_id') and evidence.get('deploy_record_sha256')==record_sha256
    except (AttributeError,TypeError): return False
def _override(candidate):
    root='/run/go-hk-deployctl'
    pathlib.Path(root).mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,path=tempfile.mkstemp(prefix='deploy-',suffix='.yaml',dir=root,text=True)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as f:
        f.write('services:\n')
        for service in SERVICES: f.write('  '+service+':\n    image: '+candidate+'\n')
    return path
def _api_healthy(runner,candidate):
    raw=_run(runner,[DOCKER,'ps','-q','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service=api'],20)
    ids=[value for value in raw.splitlines() if value]
    if len(ids)!=1: raise ValueError('api selection')
    try: data=json.loads(_run(runner,[DOCKER,'inspect',ids[0]],20))
    except Exception as exc: raise ValueError('api inspect') from exc
    if not isinstance(data,list) or len(data)!=1: raise ValueError('api inspect')
    state=data[0].get('State',{})
    if data[0].get('Image')!=candidate or not state.get('Running') or state.get('Status')!='running' or state.get('Health',{}).get('Status')!='healthy':
        raise ValueError('api readiness')
def _wait_for_api_health(runner,candidate,sleeper=time.sleep):
    for attempt in range(API_READINESS_ATTEMPTS):
        try:
            _api_healthy(runner,candidate)
            return
        except ValueError:
            if attempt + 1 == API_READINESS_ATTEMPTS:
                raise Reject('E_DEPLOY_API_READINESS_TIMEOUT')
            sleeper(API_READINESS_INTERVAL_SECONDS)
def run_deploy(release,candidate,digest,expected,binding,runner,collector,sleeper=time.sleep):
    data=_precheck(runner,candidate,digest,expected)
    collector._collect_verify(runner,expected,expected,collector.inputs_for(expected),sleeper)
    # A service-only rollback cannot restore a changed schema. Such transitions
    # require a separately designed migration/recovery operation, never this action.
    if SITE['previous']['database_head']!=SITE['candidate']['database_head']: raise Reject('E_SCHEMA_TRANSITION_REQUIRES_SEPARATE_PLAN')
    record=_record_v2(release,candidate,digest,expected,data,runner,binding)
    override=None
    try:
        try:
            override=_override(candidate)
        except OSError as exc:
            raise Reject('E_DEPLOY_TEMP_CREATION') from exc
        # Same-image deployments are intentionally a fixed, scoped recreation.
        # The flag is executor-owned: no Task parameter can add, remove, or vary it.
        _run(runner,[DOCKER,'compose','--env-file',ENV,'-p',PROJECT,'-f',COMPOSE,'-f',override,'up','-d','--no-deps','--force-recreate',*SERVICES],300)
        _,post_protected_hash=_protected_non_target_snapshot(runner)
        if post_protected_hash!=json.loads(pathlib.Path(record['record_path']).read_text(encoding='utf-8'))['protected_non_target_inventory_sha256']:
            raise Reject('E_DEPLOY_PROTECTED_NON_TARGET_MUTATION')
        if _non_target_snapshot(runner,_ids(runner))!=json.loads(pathlib.Path(record['record_path']).read_text())['non_target_container_inventory_sha256']: raise Reject('E_NON_TARGET_MUTATION')
        _wait_for_api_health(runner,candidate,sleeper)
        check=collector._collect_verify(runner,candidate,candidate,collector.inputs_for(candidate),sleeper)
        if check.get('target_service_count')!=8: raise Reject('E_DEPLOY_PARTIAL_CONVERGENCE')
        return {'durable_previous_state':'PASS','candidate_binding':'PASS','current_state':'PASS','fixed_scope':'PASS','no_migration':'PASS','post_deploy_verify':'PASS',**record}
    except Exception as exc:
        failure={'record_id':record['deploy_record_id']+'-failure','schema_version':'1','source_deploy_record_id':record['deploy_record_id'],'source_deploy_record_sha256':record['deploy_record_sha256'],'task_id':binding['task_id'],'state':'MUTATION_ATTEMPTED_OUTCOME_UNCONFIRMED','automatic_recovery':False,'error_type':type(exc).__name__}
        try: _atomic_record(failure)
        except Exception: pass  # Original immutable previous-state record remains available.
        raise DeployFailure('E_DEPLOY_ATTEMPT_FAILED_RECOVERY_REQUIRES_FRESH_AUTHORITY',record) from exc
    finally:
        if override:
            try: os.unlink(override)
            except OSError: raise Reject('E_DEPLOY_TEMP_CLEANUP')
