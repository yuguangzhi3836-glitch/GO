"""Reviewed fixed first-topology storage provisioning; no container mutation.
Binding to concrete root-reviewed authorization artifact is required before --apply.
Separate source installer must install pinned V2 helper first. No existing target
is overwritten; partial failure deliberately leaves state for reconciliation.
"""
import argparse,hashlib,importlib.util,json,os,pathlib,re,socket,stat,subprocess
HOST='iZj6ccs8t04f1p4d8pe69zZ'
IMAGE='sha256:28c8b3b34992d9d4aefb4a58d892507ef06c063d955b2da86fe0e3560013d3fe'
AUTHORIZATION_SHA256='PENDING_REVIEWED_AUTHORIZATION_BINDING'
AUTHORIZATION='/etc/go-hk-deployctl/media-topology-v2.authorization.json'
HELPER='/usr/local/libexec/go-hk-deployctl-runtime/media_topology_runtime.py'
HELPER_SHA256='080a03163389df84bc61e8b193b2eb6310898e14277573d0d27551c890e0a98d'
COMPOSE_TEXT='services:\n  api:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n  recovery-worker:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n  outbox-worker:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n  mobile-push-receipt-worker:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n  reconciliation-worker:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n  mobile-push-worker:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n  mobile-engagement-worker:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n  judgment-worker:\n    environment:\n      GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache\n    volumes:\n      - type: bind\n        source: /var/lib/go-hotel/media-cache\n        target: /var/lib/go-hotel/media-cache\n        bind:\n          create_host_path: false\n'
PROFILE={'workdir':'/workspace','revision':'0137_hosted_unknown_episode','migration_source_digest':'db20fc4e4bdf3af85b62e8090df02ea73ad66562de3bd627e185c835352c13ac'}
def require(ok,code):
 if not ok:raise ValueError(code)
def read_fixed(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  st=os.fstat(f.fileno());require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and not st.st_mode&0o022,'FIXED_FILE_PERMISSIONS');raw=f.read(1024*1024+1)
 require(len(raw)<=1024*1024,'FIXED_FILE_SIZE');return raw

def baseline_inventory(m):
 ids=[]
 for service in m.SERVICES:
  r=subprocess.run(['/usr/bin/docker','ps','-q','--no-trunc','--filter','label=com.docker.compose.project=go-822-staging','--filter','label=com.docker.compose.service='+service],check=True,capture_output=True,text=True,timeout=10);found=r.stdout.split();require(len(found)==1,'SERVICE_COUNT');ids+=found
 fmt='{{.Id}} {{.Image}} {{.State.Running}}'
 for cid in ids:
  r=subprocess.run(['/usr/bin/docker','inspect','--format',fmt,cid],check=True,capture_output=True,text=True,timeout=10);parts=r.stdout.split();require(len(parts)==3 and parts[0]==cid and parts[1]==IMAGE and parts[2]=='true','BASELINE_IMAGE_DRIFT')
  r=subprocess.run(['/usr/bin/docker','inspect','--format','{{json .Mounts}}',cid],check=True,capture_output=True,text=True,timeout=10);require(json.loads(r.stdout)==[],'BASELINE_MOUNT_DRIFT')
 return ids

def main(apply=False):
 # Reject before host/process/file access while preparation is unbound.
 require(re.fullmatch('[0-9a-f]{64}',AUTHORIZATION_SHA256) is not None and re.fullmatch('[0-9a-f]{64}',HELPER_SHA256) is not None,'PREPARATION_NOT_BOUND')
 require(socket.gethostname()==HOST and os.geteuid()==0,'HOST_OR_UID_MISMATCH')
 raw=read_fixed(HELPER);require(hashlib.sha256(raw).hexdigest()==HELPER_SHA256,'HELPER_SOURCE_DRIFT')
 spec=importlib.util.spec_from_file_location('media_topology_runtime',HELPER);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 m.trusted_ancestors(str(pathlib.Path(HELPER).parent));m.trusted_ancestors('/etc/go-hk-deployctl');m.trusted_ancestors('/var/lib')
 raw=read_fixed(AUTHORIZATION);require(hashlib.sha256(raw).hexdigest()==AUTHORIZATION_SHA256,'AUTHORIZATION_ARTIFACT_DRIFT')
 authorization=json.loads(raw)
 # The artifact is independently reviewed and frozen by root, not self-issued here.
 require(authorization.get('schema')=='go.hk-media-topology-authorization.v1' and authorization.get('action')=='HK_STAGING_TOPOLOGY_V1_TO_V2_FIRST_INSTALL' and authorization.get('topology_sha256')==m.TOPOLOGY_SHA and authorization.get('expected_image_id')==IMAGE and authorization.get('cache_path')==m.CACHE and authorization.get('source_helper_sha256')==HELPER_SHA256,'AUTHORIZATION_SCOPE')
 require(hashlib.sha256(COMPOSE_TEXT.encode()).hexdigest()==m.COMPOSE_SHA,'COMPOSE_PAYLOAD_DRIFT')
 baseline_inventory(m)
 for path in [m.CACHE,m.COMPOSE,m.INSTALLATION]:require(not os.path.lexists(path),'TARGET_EXISTS_NO_OVERWRITE')
 parent=pathlib.Path(m.CACHE).parent
 if parent.exists() or parent.is_symlink():m.trusted_ancestors(str(parent))
 r=subprocess.run(['/usr/bin/findmnt','--target',str(parent if parent.exists() else parent.parent),'--noheadings','--output','FSTYPE'],check=True,capture_output=True,text=True,timeout=10);require(r.stdout.strip() in {'ext4','xfs','btrfs'},'HOST_LOCAL_FILESYSTEM_REQUIRED')
 if not apply:return {'status':'PREFLIGHT_PASS_NO_WRITES','topology_sha256':m.TOPOLOGY_SHA}
 # No data copy/reset, service restart or compose invocation. Only first install leaves.
 if not parent.exists():parent.mkdir(mode=0o755)
 m.trusted_ancestors(str(parent))
 identity=m.bootstrap_new_cache(m.TOPOLOGY_SHA)
 for path,raw in [(m.COMPOSE,COMPOSE_TEXT.encode()),(m.INSTALLATION,m.canonical({'schema':'go.hk-media-topology-installation.v1','topology_id':m.TOPOLOGY_ID,'topology_version':2,'topology_sha256':m.TOPOLOGY_SHA,'compose_sha256':m.COMPOSE_SHA,'media_storage_identity':identity,'authorization_sha256':AUTHORIZATION_SHA256,'runtime_profile':PROFILE,'baseline_image_id':IMAGE}))]:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  fd=os.open(str(pathlib.Path(path).parent),os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
 require(m.installed()['media_storage_identity']==identity,'INSTALLATION_READBACK')
 return {'status':'STORAGE_PREPARED_NOT_ACTIVATED','topology_sha256':m.TOPOLOGY_SHA,'media_storage_identity':identity,'container_mutation':False}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');a=parser.parse_args()
 try:print(json.dumps(main(a.apply)))
 except Exception as exc:raise SystemExit(str(exc) if isinstance(exc,ValueError) else 'TOPOLOGY_PREPARATION_FAILED')
