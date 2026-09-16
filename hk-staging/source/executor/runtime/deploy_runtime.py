"""Fixed, fail-closed HK-STAGING DEPLOY runtime.  No caller controls Docker argv."""
import hashlib,json,os,pathlib,re,secrets,tempfile,time

DOCKER='/usr/bin/docker'; PROJECT='go-822-staging'
COMPOSE='/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml'
ENV='/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env'
COMPOSE_SHA='7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895'
ENV_SHA='6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc'
RECORD_DIR='/var/lib/go-hk-deployctl/deploy-records'
SERVICES=('api','recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker')
IMAGE=re.compile(r'^sha256:[0-9a-f]{64}$'); DIGEST=re.compile(r'^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$')
TASK_ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'); NONCE=re.compile(r'^[A-Za-z0-9_-]{1,128}$'); SHA256=re.compile(r'^[0-9a-f]{64}$')
API_READINESS_ATTEMPTS=12
API_READINESS_INTERVAL_SECONDS=5

class Reject(ValueError): pass
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
def _precheck(runner,candidate,package,expected,artifact):
    if not IMAGE.fullmatch(candidate): raise Reject('E_DEPLOY_CANDIDATE_IMAGE')
    if not IMAGE.fullmatch(expected): raise Reject('E_DEPLOY_EXPECTED_IMAGE')
    if not SHA256.fullmatch(package): raise Reject('E_DEPLOY_CANDIDATE_PACKAGE')
    if _sha(COMPOSE)!=COMPOSE_SHA: raise Reject('E_DEPLOY_COMPOSE_DRIFT')
    if _sha(ENV)!=ENV_SHA: raise Reject('E_DEPLOY_ENV_DRIFT')
    # The candidate arrives as a sealed package rather than as something that has
    # to be lying around already. Resolving and loading it IS the delivery step,
    # and it only completes once Docker reports the candidate image id; a registry
    # digest was never satisfiable here, because a manifest digest is not an image
    # config ID and a host-built image has no digest at all.
    artifact.materialise(runner,package,candidate)
    data=_inspect(runner,_ids(runner))
    if any(x.get('Image')!=expected for x in data): raise Reject('E_DEPLOY_CURRENT_IMAGE_DRIFT')
    return data
def _task_binding(binding):
    if not isinstance(binding,dict) or set(binding)!={'task_id','nonce','authority','canonical_sha256'}: raise Reject('E_DEPLOY_TASK_BINDING')
    if not TASK_ID.fullmatch(binding['task_id']) or not NONCE.fullmatch(binding['nonce']): raise Reject('E_DEPLOY_TASK_BINDING')
    if binding['authority']!='GO-COMMAND-CENTER' or not SHA256.fullmatch(binding['canonical_sha256']): raise Reject('E_DEPLOY_TASK_BINDING')
    return dict(binding)
def _repo_digest(runner,image):
    values=[v for v in _run(runner,[DOCKER,'image','inspect',image,'--format','{{join .RepoDigests "\\n"}}'],20).splitlines() if DIGEST.fullmatch(v) and v.endswith(image[7:])]
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
def _record_v2(release,candidate,package,expected,data,runner,binding):
    binding=_task_binding(binding)
    targets=[]
    for service,container in zip(SERVICES,data):
        labels=container.get('Config',{}).get('Labels',{})
        image=container.get('Image')
        if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service or not isinstance(container.get('Id'),str) or not IMAGE.fullmatch(image or ''): raise Reject('E_DEPLOY_TARGET_BINDING')
        targets.append({'service':service,'container_id':container['Id'],'image_id':image,'repo_digest':_repo_digest(runner,image)})
    record_identity=hashlib.sha256(json.dumps({'task_id':binding['task_id'],'nonce':binding['nonce'],'release_id':release},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    protected_inventory,protected_hash=_protected_non_target_snapshot(runner)
    record={'deploy_record_schema_version':'2','record_id':record_identity,'created_at':int(time.time()),'environment':'HK-STAGING-01','action_id':'HK_STAGING_DEPLOY','task_id':binding['task_id'],'nonce':binding['nonce'],'authority':binding['authority'],'task_canonical_sha256':binding['canonical_sha256'],'release_id':release,'candidate_image_id':candidate,'candidate_package_sha256':package,'expected_current_image_id':expected,'compose_path':COMPOSE,'compose_sha256':COMPOSE_SHA,'runtime_env_path':ENV,'env_sha256':ENV_SHA,'target_count':8,'targets':targets,'non_target_container_inventory_sha256':_non_target_snapshot(runner,[x['container_id'] for x in targets]),'protected_non_target_inventory':protected_inventory,'protected_non_target_inventory_sha256':protected_hash}
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
def run_deploy(release,candidate,package,expected,binding,runner,collector,artifact,sleeper=time.sleep):
    data=_precheck(runner,candidate,package,expected,artifact)
    record=_record_v2(release,candidate,package,expected,data,runner,binding)
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
        _wait_for_api_health(runner,candidate,sleeper)
        check=collector._collect_verify(runner,candidate,candidate,collector._PRODUCTION_VERIFY_INPUTS,sleeper)
        if check.get('target_service_count')!=8: raise Reject('E_DEPLOY_PARTIAL_CONVERGENCE')
        return {'durable_previous_state':'PASS','candidate_binding':'PASS','current_state':'PASS','fixed_scope':'PASS','no_migration':'PASS','post_deploy_verify':'PASS',**record}
    finally:
        if override:
            try: os.unlink(override)
            except OSError: raise Reject('E_DEPLOY_TEMP_CLEANUP')
