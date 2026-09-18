"""Topology V2 media contract primitives. No CLI, auto-install or authority bypass.
The formal executor must authenticate/authorize a topology transition before bootstrap.
"""
import hashlib,json,os,pathlib,re,stat
TOPOLOGY_ID='HK_STAGING_BUSINESS_TOPOLOGY'
TOPOLOGY_VERSION=2
CACHE='/var/lib/go-hotel/media-cache'
MARKER='.go-media-topology-v2.json'
SERVICES=('api','recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker')
PROTECTED=('redis','caddy')
class Reject(ValueError):pass

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def require(ok,code):
 if not ok:raise Reject(code)
def directory_fd(path):
 """Open every absolute path component O_NOFOLLOW; never resolve across a symlink."""
 p=pathlib.PurePosixPath(path)
 require(p.is_absolute() and '..' not in p.parts and str(p)==path,'MEDIA_PATH_INVALID')
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
 try:
  for part in p.parts[1:]:
   nextfd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nextfd
  return fd
 except BaseException:os.close(fd);raise

def marker_payload(contract_sha):
 require(isinstance(contract_sha,str) and len(contract_sha)==64 and all(c in '0123456789abcdef' for c in contract_sha),'TOPOLOGY_CONTRACT_HASH_INVALID')
 return {'topology_id':TOPOLOGY_ID,'topology_version':2,'contract_sha256':contract_sha,'cache_path':CACHE,'storage_kind':'HOST_LOCAL_BIND','contents':['index.sqlite3','files/'],'destructive_reset_allowed':False}

def bootstrap_new_cache(contract_sha):
 """Called only by separately authorized first-topology installation, never normal DEPLOY.
 Parent must exist and be proven host-local by formal installation evidence.
 Existing leaf (even empty directory or dangling symlink) is never reused/overwritten.
 """
 expected=marker_payload(contract_sha);path=pathlib.PurePosixPath(CACHE)
 parent=directory_fd(str(path.parent))
 try:
  try:os.mkdir(path.name,0o700,dir_fd=parent)
  except FileExistsError as exc:raise Reject('MEDIA_TARGET_EXISTS_NO_OVERWRITE') from exc
  fd=os.open(path.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
  try:
   mf=os.open(MARKER,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400,dir_fd=fd)
   with os.fdopen(mf,'wb') as f:f.write(canonical(expected));f.flush();os.fsync(f.fileno())
   os.fsync(fd);os.fsync(parent)
  finally:os.close(fd)
 finally:os.close(parent)
 return storage_identity(contract_sha)

def storage_identity(contract_sha):
 fd=directory_fd(CACHE)
 try:
  info=os.fstat(fd);mf=os.open(MARKER,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
  with os.fdopen(mf,'rb') as f:
   require(stat.S_ISREG(os.fstat(f.fileno()).st_mode),'MEDIA_MARKER_TYPE');raw=f.read(8193)
  require(raw==canonical(marker_payload(contract_sha)),'MEDIA_MARKER_OR_CONTRACT_DRIFT')
  return {'topology_id':TOPOLOGY_ID,'topology_version':2,'contract_sha256':contract_sha,'host_path':CACHE,'container_path':CACHE,'device':info.st_dev,'inode':info.st_ino,'marker_sha256':hashlib.sha256(raw).hexdigest()}
 finally:os.close(fd)

def validate_runtime_mounts(containers,expected_image):
 """Pass the fixed eight-service inventory already collected by the executor.
 Never accept caller-selected mount paths, service lists or environment overrides.
 """
 require(isinstance(expected_image,str) and re.fullmatch(r'sha256:[0-9a-f]{64}',expected_image),'TOPOLOGY_IMAGE_INVALID')
 require(len(containers)==8,'TOPOLOGY_SERVICE_COUNT')
 found=set()
 for item in containers:
  cfg=item.get('Config',{});labels=cfg.get('Labels',{});service=labels.get('com.docker.compose.service')
  require(service in SERVICES and service not in found and labels.get('com.docker.compose.project')=='go-822-staging','TOPOLOGY_SERVICE_SET')
  found.add(service);require(item.get('Image')==expected_image,'TOPOLOGY_IMAGE_DRIFT')
  env=[v.split('=',1)[1] for v in cfg.get('Env',[]) if v.startswith('GO_MEDIA_CACHE_DIR=')]
  require(env==[CACHE],'MEDIA_ENV_PATH_DRIFT')
  mounts=[m for m in item.get('Mounts',[]) if pathlib.PurePosixPath(CACHE).is_relative_to(pathlib.PurePosixPath(m.get('Destination','/invalid'))) or pathlib.PurePosixPath(m.get('Destination','/invalid')).is_relative_to(pathlib.PurePosixPath(CACHE))]
  require(len(mounts)==1,'MEDIA_MOUNT_MISSING_OR_SHADOWED')
  m=mounts[0];require(m.get('Type')=='bind' and m.get('Source')==CACHE and m.get('Destination')==CACHE and m.get('RW') is True,'MEDIA_MOUNT_DRIFT')
 return {'topology_id':TOPOLOGY_ID,'topology_version':2,'media_mounts':'PASS','service_count':8}

def require_record_binding(record,identity):
 require(record.get('topology_id')==TOPOLOGY_ID and record.get('topology_version')==2 and record.get('topology_sha256')==TOPOLOGY_SHA,'TOPOLOGY_RECORD_REQUIRED')
 require(record.get('media_storage_identity')==identity,'MEDIA_STORAGE_IDENTITY_DRIFT')
 return True

def require_preserved(before,after,protected_before,protected_after):
 require(before==after,'MEDIA_STORAGE_IDENTITY_DRIFT')
 require(protected_before==protected_after,'PROTECTED_NON_TARGET_MUTATION')
 return {'media_storage_preserved':'PASS','protected_non_targets':'PASS'}

# Fixed installation metadata is source-maintenance evidence, never a caller option.
# It must be installed under separately reviewed first-topology authority.
INSTALLATION='/etc/go-hk-deployctl/media-topology-v2.installation.json'
AUTHORIZATION='/etc/go-hk-deployctl/media-topology-v2.authorization.json'
COMPOSE='/etc/go-hk-deployctl/media-topology-v2.compose.yml'
TOPOLOGY_SHA='3efa422ebcfeee97528e829228a5f1c78a91151c88c50c606bab95479f3fddb1'
COMPOSE_SHA='a155a761d2aec58402d5bc648048166950d20be3410df66aa540af082d195351'

def secure_bytes(path):
 parent=directory_fd(str(pathlib.PurePosixPath(path).parent))
 try:
  fd=os.open(pathlib.PurePosixPath(path).name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=parent)
  with os.fdopen(fd,'rb') as f:
   st=os.fstat(f.fileno());require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and not st.st_mode&0o022,'TOPOLOGY_INSTALLATION_PERMISSIONS');raw=f.read(65537)
  require(len(raw)<=65536,'TOPOLOGY_INSTALLATION_SIZE');return raw
 finally:os.close(parent)

def installed():
 if not os.path.lexists(INSTALLATION):return None
 trusted_ancestors(str(pathlib.Path(INSTALLATION).parent));trusted_ancestors(str(pathlib.Path(COMPOSE).parent));trusted_ancestors(CACHE)
 value=json.loads(secure_bytes(INSTALLATION))
 require(set(value)=={'schema','topology_id','topology_version','topology_sha256','compose_sha256','media_storage_identity','authorization_sha256','runtime_profile','baseline_image_id'},'TOPOLOGY_INSTALLATION_FIELDS')
 require(value['schema']=='go.hk-media-topology-installation.v1' and value['topology_id']==TOPOLOGY_ID and value['topology_version']==2 and value['topology_sha256']==TOPOLOGY_SHA and value['compose_sha256']==COMPOSE_SHA,'TOPOLOGY_INSTALLATION_BINDING')
 require(re.fullmatch('[0-9a-f]{64}',value['authorization_sha256'] or ''),'TOPOLOGY_INSTALLATION_AUTHORITY_BINDING')
 authorization_raw=secure_bytes(AUTHORIZATION);require(hashlib.sha256(authorization_raw).hexdigest()==value['authorization_sha256'],'TOPOLOGY_AUTHORIZATION_ARTIFACT_DRIFT')
 authorization=json.loads(authorization_raw)
 require(authorization.get('schema')=='go.hk-media-topology-authorization.v1' and authorization.get('action')=='HK_STAGING_TOPOLOGY_V1_TO_V2_FIRST_INSTALL' and authorization.get('topology_sha256')==TOPOLOGY_SHA and authorization.get('expected_image_id')==value['baseline_image_id'] and authorization.get('cache_path')==CACHE and authorization.get('source_helper_sha256')==hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'TOPOLOGY_AUTHORIZATION_SCOPE')
 require(re.fullmatch('sha256:[0-9a-f]{64}',value['baseline_image_id'] or ''),'TOPOLOGY_BASELINE_IMAGE')
 profile=value['runtime_profile'];require(isinstance(profile,dict) and set(profile)=={'workdir','revision','migration_source_digest'} and profile['workdir']=='/workspace' and re.fullmatch('[0-9][0-9a-z_]{1,79}',profile['revision'] or '') and re.fullmatch('[0-9a-f]{64}',profile['migration_source_digest'] or ''),'TOPOLOGY_RUNTIME_PROFILE')
 fd=os.open(COMPOSE,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  st=os.fstat(f.fileno());require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and not st.st_mode&0o022,'TOPOLOGY_COMPOSE_PERMISSIONS');raw=f.read(131073)
 require(len(raw)<=131072 and hashlib.sha256(raw).hexdigest()==COMPOSE_SHA,'TOPOLOGY_COMPOSE_DRIFT')
 require(storage_identity(TOPOLOGY_SHA)==value['media_storage_identity'],'TOPOLOGY_STORAGE_DRIFT')
 return value

def descriptor(contract):
 return contract.get('topology') if isinstance(contract,dict) else None

def require_descriptor(contract):
 topo=descriptor(contract)
 require(isinstance(topo,dict) and set(topo)=={'topology_id','topology_version','topology_sha256','baseline_topology_version','media_rollback_compatible'},'TOPOLOGY_CONTRACT_REQUIRED')
 require(topo['topology_id']==TOPOLOGY_ID and topo['topology_version']==2 and topo['topology_sha256']==TOPOLOGY_SHA and type(topo['baseline_topology_version']) is int and topo['baseline_topology_version'] in (1,2) and topo['media_rollback_compatible'] is True,'TOPOLOGY_CONTRACT_MISMATCH')
 require(contract.get('migration_required') is False and contract.get('baseline_revision')==contract.get('target_revision') and contract.get('migration_source_digest')==contract.get('baseline_migration_source_digest'),'TOPOLOGY_NO_MIGRATION_REQUIRED')
 return topo

def predeploy(contract,containers,expected_image):
 installation=installed();topo=descriptor(contract)
 if installation is None:
  require(topo is None,'TOPOLOGY_CHANGE_REQUIRED');return None
 topo=require_descriptor(contract)
 require(contract['baseline_revision']==installation['runtime_profile']['revision'] and contract['migration_source_digest']==installation['runtime_profile']['migration_source_digest'],'TOPOLOGY_PROFILE_DRIFT')
 if topo['baseline_topology_version']==2:validate_runtime_mounts(containers,expected_image)
 else:
  require(not transition_started() and expected_image==installation['baseline_image_id'],'TOPOLOGY_TRANSITION_BASELINE_DRIFT')
  # First transition accepts only the observed original eight-role unmounted state.
  require(len(containers)==8,'TOPOLOGY_SERVICE_COUNT');seen=set()
  for item in containers:
   labels=item.get('Config',{}).get('Labels',{});service=labels.get('com.docker.compose.service')
   require(service in SERVICES and service not in seen and labels.get('com.docker.compose.project')=='go-822-staging' and item.get('Image')==expected_image,'TOPOLOGY_BASELINE_SCOPE');seen.add(service)
   require(not item.get('Mounts'),'TOPOLOGY_BASELINE_MOUNT_DRIFT')
 return installation['media_storage_identity']

def verify(containers,image,allow_unmounted_baseline=False):
 installation=installed()
 if installation is None:return {}
 if allow_unmounted_baseline and not transition_started() and image==installation['baseline_image_id']:
  require(len(containers)==8 and {x.get('Config',{}).get('Labels',{}).get('com.docker.compose.service') for x in containers}==set(SERVICES) and all(not x.get('Mounts') and x.get('Image')==image and x.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')=='go-822-staging' for x in containers),'TOPOLOGY_BASELINE_DRIFT')
  return {'topology_id':TOPOLOGY_ID,'topology_version':1,'topology_pending_version':2,'media_persistence':'NOT_ACTIVE'}
 validate_runtime_mounts(containers,image)
 return {'topology_id':TOPOLOGY_ID,'topology_version':2,'topology_sha256':TOPOLOGY_SHA,'media_storage_identity':installation['media_storage_identity'],'media_persistence':'PASS'}

def compose_args(identity):return ['-f',COMPOSE] if identity is not None else []

def record_fields(identity,contract):
 if identity is None:return {}
 require_descriptor(contract)
 return {'topology_id':TOPOLOGY_ID,'topology_version':2,'topology_sha256':TOPOLOGY_SHA,'baseline_topology_version':contract['topology']['baseline_topology_version'],'media_storage_identity':identity,'media_rollback_compatible':True}

def postdeploy(before,containers,image):
 if before is None:return {}
 result=verify(containers,image);require(result['media_storage_identity']==before,'MEDIA_STORAGE_IDENTITY_DRIFT');return result

TRANSITION_MARKER='.go-media-topology-v2-transition.json'
def transition_started():
 fd=directory_fd(CACHE)
 try:
  try:mf=os.open(TRANSITION_MARKER,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
  except FileNotFoundError:return False
  with os.fdopen(mf,'rb') as f:
   st=os.fstat(f.fileno());require(st.st_uid==0 and stat.S_ISREG(st.st_mode) and not st.st_mode&0o022,'TOPOLOGY_TRANSITION_PERMISSIONS');raw=f.read(8193)
  value=json.loads(raw);require(set(value)=={'topology_sha256','source_deploy_record_sha256'} and value['topology_sha256']==TOPOLOGY_SHA and re.fullmatch('[0-9a-f]{64}',value['source_deploy_record_sha256'] or ''),'TOPOLOGY_TRANSITION_BINDING')
  return True
 finally:os.close(fd)

def begin(identity,contract,record):
 if identity is None:return
 if contract['topology']['baseline_topology_version']==2:
  require(transition_started(),'TOPOLOGY_TRANSITION_RECORD_REQUIRED');return
 require(not transition_started(),'TOPOLOGY_TRANSITION_ALREADY_STARTED')
 payload={'topology_sha256':TOPOLOGY_SHA,'source_deploy_record_sha256':record['deploy_record_sha256']}
 fd=directory_fd(CACHE)
 try:
  mf=os.open(TRANSITION_MARKER,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400,dir_fd=fd)
  with os.fdopen(mf,'wb') as f:f.write(canonical(payload));f.flush();os.fsync(f.fileno())
  os.fsync(fd)
 finally:os.close(fd)

def inventory(runner):
 ids=[]
 for service in SERVICES:
  result=runner.run(['/usr/bin/docker','ps','-q','--filter','label=com.docker.compose.project=go-822-staging','--filter','label=com.docker.compose.service='+service])
  found=result.stdout.split();require(result.returncode==0 and len(found)==1,'TOPOLOGY_INVENTORY_COUNT');ids+=found
 result=runner.run(['/usr/bin/docker','inspect',*ids]);require(result.returncode==0,'TOPOLOGY_INVENTORY_READ')
 return json.loads(result.stdout)

def canary_preflight(contract,runner,expected_image):
 if descriptor(contract) is None:
  require(installed() is None,'TOPOLOGY_CONTRACT_REQUIRED');return {}
 identity=predeploy(contract,inventory(runner),expected_image)
 return {'topology_preflight':'PASS','topology_id':TOPOLOGY_ID,'topology_version':2,'topology_sha256':TOPOLOGY_SHA,'media_storage_identity':identity}

def trusted_ancestors(path):
 p=pathlib.Path(path)
 for ancestor in (p,*p.parents):
  st=ancestor.lstat()
  require(stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode) and st.st_uid==0 and not st.st_mode&0o022,'TOPOLOGY_UNTRUSTED_ANCESTOR')
