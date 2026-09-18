"""Read-only, host-pinned, fixed-file SHA256 and metadata. No config export.
Review candidate only: do not execute remotely before root/C13 approval.
"""
import datetime,hashlib,json,os,socket,stat,sys

HOSTS={'go-cc':'iZj6c7k6k01biwlbnwutu5Z','hk-staging':'iZj6ccs8t04f1p4d8pe69zZ'}
# Injected fixed allowlist at local preparation; no arbitrary path argument.
FIXED_PATHS = {'go-cc': ['/etc/go-command-center/active-candidate-v1.json', '/etc/go-command-center/boss-request-bridge-v1.json', '/etc/go-command-center/boss-request-canary-baseline-v1.json', '/etc/go-command-center/boss-request-verify-baseline-v1.json', '/etc/go-command-center/candidate-contracts-v1/23d78ea846b21ace5318335eacb2a75826db5ff56cd925c8f8c58f6a83babed6.json', '/etc/go-command-center/candidate-contracts-v1/36622f0648051d57d5918ea4ff7b9ac4e74f9c686e8f2c503f66bda15bd4b120.json', '/etc/go-command-center/candidate-contracts-v1/474dc4edaf3e9e222176d324d8116ae295c381a382ae8545bb82eddb6b7241c5.json', '/etc/go-command-center/candidate-contracts-v1/d0a4d82a1e56e7ff96ddedc1668534f57961aab6875ca9c0f7997d37e72b56fb.json', '/etc/systemd/system/go-boss-request-bridge.service', '/opt/go-command-center/state-publication-v1/installed.json', '/usr/local/libexec/execution_window.py', '/usr/local/libexec/go-boss-request-bridge', '/usr/local/libexec/go_deploy_request.py', '/usr/local/libexec/hk_candidate_contract.py', '/usr/local/libexec/plan_derivation.py'], 'hk-staging': ['/etc/go-hk-agent/agent.json', '/etc/go-hk-deployctl/candidate-contracts-v1/23d78ea846b21ace5318335eacb2a75826db5ff56cd925c8f8c58f6a83babed6.json', '/etc/go-hk-deployctl/candidate-contracts-v1/36622f0648051d57d5918ea4ff7b9ac4e74f9c686e8f2c503f66bda15bd4b120.json', '/etc/go-hk-deployctl/candidate-contracts-v1/474dc4edaf3e9e222176d324d8116ae295c381a382ae8545bb82eddb6b7241c5.json', '/etc/go-hk-deployctl/candidate-contracts-v1/d0a4d82a1e56e7ff96ddedc1668534f57961aab6875ca9c0f7997d37e72b56fb.json', '/etc/systemd/system/go-hk-agent.service', '/etc/systemd/system/go-hk-agent.timer', '/opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py', '/opt/go-hk-agent-rebuilt/hk_agent/execution_window.py', '/opt/go-hk-agent-rebuilt/hk_agent/test_pr.py', '/opt/go-hk-agent-rebuilt/hk_agent/transport.py', '/usr/local/libexec/go-hk-deployctl', '/usr/local/libexec/go-hk-deployctl-runtime/artifact_runtime.py', '/usr/local/libexec/go-hk-deployctl-runtime/canary_runtime.py', '/usr/local/libexec/go-hk-deployctl-runtime/collector_runtime.py', '/usr/local/libexec/go-hk-deployctl-runtime/deploy_runtime.py', '/usr/local/libexec/go-hk-deployctl-runtime/hk_candidate_contract.py', '/usr/local/libexec/go-hk-deployctl-runtime/media_topology_runtime.py', '/usr/local/libexec/go-hk-deployctl-runtime/migration_program.py', '/usr/local/libexec/go-hk-deployctl-runtime/migration_runtime.py', '/usr/local/libexec/go-hk-deployctl-runtime/rollback_runtime.py', '/usr/local/libexec/go-hk-deployctl-runtime/same_revision_program.py', '/usr/local/libexec/go-hk-deployctl-runtime/same_revision_runtime.py']}
MAX_FILE_BYTES=4*1024*1024

class Reject(ValueError):pass

def directory_metadata(fd):
 s=os.fstat(fd)
 if not stat.S_ISDIR(s.st_mode):raise Reject('ancestor_not_directory')
 return {'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode),'directory':True}

def stable(s):
 return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)

def hash_file(name,directories):
 # Walk each directory with O_NOFOLLOW; never traverse a directory symlink.
 parts=name.split('/')
 if parts[0]!='' or any(p in ('','.','..') for p in parts[1:]):raise Reject('fixed_path_invalid')
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 opened=[fd]
 try:
  path='/'
  for component in [None,*parts[1:-1]]:
   if component is not None:
    fd=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);opened.append(fd)
    path=path.rstrip('/')+'/'+component
   metadata=directory_metadata(fd)
   if path in directories and directories[path]!=metadata:raise Reject('ancestor_drift_during_read')
   directories[path]=metadata
  try:file_fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
  except FileNotFoundError:
   if name!='/usr/local/libexec/go-hk-deployctl-runtime/media_topology_runtime.py':raise
   return {'exists':False}
  opened.append(file_fd);before=os.fstat(file_fd)
  if not stat.S_ISREG(before.st_mode) or not 0<=before.st_size<=MAX_FILE_BYTES:raise Reject('fixed_file_type_or_size')
  h=hashlib.sha256();count=0
  while True:
   chunk=os.read(file_fd,65536)
   if not chunk:break
   count+=len(chunk)
   if count>MAX_FILE_BYTES:raise Reject('fixed_file_grew')
   h.update(chunk)
  if stable(before)!=stable(os.fstat(file_fd)) or count!=before.st_size:raise Reject('fixed_file_changed_during_read')
  return {'sha256':h.hexdigest(),'uid':before.st_uid,'gid':before.st_gid,'mode':stat.S_IMODE(before.st_mode),'regular':True}
 finally:
  for handle in reversed(opened):os.close(handle)

def observe(host):
 if host not in HOSTS or HOSTS[host].startswith('PENDING'):raise Reject('host_pin_unsealed')
 if socket.gethostname()!=HOSTS[host]:raise Reject('hostname_mismatch')
 if os.geteuid()!=0:raise Reject('root_read_required')
 paths=FIXED_PATHS[host]
 if len(paths)!=len(set(paths)):raise Reject('duplicate_fixed_path')
 directories={};files={name:hash_file(name,directories) for name in paths}
 if socket.gethostname()!=HOSTS[host]:raise Reject('hostname_changed')
 return {'schema':'go.candidate.hash-only-preflight.v1','host':host,'hostname':HOSTS[host],
         'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'files':files,'directories':directories,'content_exported':False,
         'permissions_changed':False,'runtime_commands_executed':False,
         'note':'New candidate contract absence is a separate fixed-target check after identity is known.'}

def main():
 if len(sys.argv)!=2:raise Reject('arguments')
 print(json.dumps(observe(sys.argv[1]),sort_keys=True))

if __name__=='__main__':
 try:main()
 except Exception as exc:
  # Never dump file bytes, tracebacks or exception objects from reads.
  print(json.dumps({'result':'PREFLIGHT_REJECTED','error_type':type(exc).__name__}))
  raise SystemExit(2)
