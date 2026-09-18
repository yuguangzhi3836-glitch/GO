"""Review-only until invoked with --apply; fixed source maintenance, no Task.

Only ten source paths can change. Existing ownership and permissions are retained.
No candidate admission, signing, permission, deployment or database changes.
"""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import socket
import subprocess
import sys

MANIFEST_SHA256 = 'PENDING_FRESH_MANIFEST'
TARGETS = {'go-cc': {'control-plane/boss-deploy-request-v1/hk_candidate_contract.py': '/usr/local/libexec/hk_candidate_contract.py', 'control-plane/boss-deploy-request-v1/go_deploy_request.py': '/usr/local/libexec/go_deploy_request.py', 'control-plane/boss-deploy-request-v1/plan_derivation.py': '/usr/local/libexec/plan_derivation.py'}, 'hk-staging': {'hk-staging/source/executor/go-hk-deployctl': '/usr/local/libexec/go-hk-deployctl', 'hk-staging/source/executor/runtime/hk_candidate_contract.py': '/usr/local/libexec/go-hk-deployctl-runtime/hk_candidate_contract.py', 'hk-staging/source/executor/runtime/deploy_runtime.py': '/usr/local/libexec/go-hk-deployctl-runtime/deploy_runtime.py', 'hk-staging/source/executor/runtime/same_revision_runtime.py': '/usr/local/libexec/go-hk-deployctl-runtime/same_revision_runtime.py', 'hk-staging/source/executor/runtime/collector_runtime.py': '/usr/local/libexec/go-hk-deployctl-runtime/collector_runtime.py', 'hk-staging/source/executor/runtime/rollback_runtime.py': '/usr/local/libexec/go-hk-deployctl-runtime/rollback_runtime.py', 'hk-staging/source/executor/runtime/media_topology_runtime.py': '/usr/local/libexec/go-hk-deployctl-runtime/media_topology_runtime.py'}}
UNITS = {'go-cc':['go-boss-request-bridge.service','go-command-center-state-cycle.service'],
         'hk-staging':['go-hk-agent.service']}
SMOKE = {
 'go-cc': "import sys,runpy;sys.path.insert(0,'/usr/local/libexec');import go_deploy_request,plan_derivation,hk_candidate_contract;assert hk_candidate_contract.active() is not None;runpy.run_path('/usr/local/libexec/go-boss-request-bridge',run_name='integrity_only');print('IMPORT_AND_LEGACY_CONTRACT_PASS')",
 'hk-staging': "import runpy;d=runpy.run_path('/usr/local/libexec/go-hk-deployctl',run_name='integrity_only');assert d['VERSION']=='0.6.0-media-topology-v2';[d[n]() for n in ['_load_collector','_load_canary','_load_deploy','_load_rollback','_load_artifact','_migration']];d['_same_revision']().program();d['_topology']();print('IMPORT_AND_ALL_PINS_PASS')"
}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def run(argv,check=True):return subprocess.run(argv,capture_output=True,text=True,check=check,timeout=45)
def state(unit):return run(['systemctl','is-active',unit],False).stdout.strip()

def info(name):
 p=Path(name)
 if not p.exists() and not p.is_symlink():return {'exists':False}
 s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or p.is_symlink():raise ValueError('source_type:'+name)
 return {'sha256':digest(p.read_bytes()),'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'regular':True}

def safe_parent(path):
 for p in (path,*path.parents):
  s=p.lstat()
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('untrusted_parent:'+str(p))

def directory_info(path):
 s=Path(path).lstat()
 if not stat.S_ISDIR(s.st_mode):raise ValueError('guard_ancestor_type:'+str(path))
 return {'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode),'directory':True}

def guard_check(guards,ancestors):
 required={str(p) for name in guards for p in Path(name).parents}
 if set(ancestors)!=required:raise ValueError('guard_ancestor_set')
 for name,expected in ancestors.items():
  if directory_info(name)!=expected:raise ValueError('guard_ancestor_drift:'+name)
 for name,expected in guards.items():
  if info(name)!=expected:raise ValueError('protected_baseline_moved:'+name)
 return True

def sync(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)

def write_new(path,raw,metadata):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:
  os.fchown(f.fileno(),metadata['uid'],metadata['gid'])
  os.fchmod(f.fileno(),metadata['mode'])
  f.write(raw);f.flush();os.fsync(f.fileno())

def after_info(entry):
 old=entry['before']
 return {'sha256':entry['sha256'],'mode':0o644 if old.get('exists') is False else old['mode'],
         'uid':0 if old.get('exists') is False else old['uid'],
         'gid':0 if old.get('exists') is False else old['gid'],'regular':True}

def validate(package,host):
 if MANIFEST_SHA256.startswith('PENDING'):raise ValueError('unsealed_source_manifest')
 if set(package)!={'manifest','files'}:raise ValueError('package_fields')
 manifest=package['manifest']
 if digest(canonical(manifest))!=MANIFEST_SHA256:raise ValueError('manifest_pin')
 if set(package['files'])!={s for mapping in TARGETS.values() for s in mapping}:raise ValueError('source_set')
 entries=manifest['hosts'][host]['files'];guards=manifest['hosts'][host]['guards']
 if {e['source']:e['target'] for e in entries}!=TARGETS[host]:raise ValueError('target_set')
 if len(entries)!=len(TARGETS[host]):raise ValueError('duplicate_target')
 for e in entries:
  raw=package['files'][e['source']].encode()
  if digest(raw)!=e['sha256']:raise ValueError('source_hash')
  compile(raw,e['source'],'exec')
  safe_parent(Path(e['target']).parent)
  if info(e['target'])!=e['before']:raise ValueError('source_baseline_moved:'+e['target'])
  old=e['before']
  if old.get('exists') is not False and (old['uid']!=0 or old['mode']&0o022):raise ValueError('source_owner')
 # Guard-only paths retain their observed owner/mode, including the Agent-owned
 # /etc/go-hk-agent directory. No such exception applies to writable targets.
 guard_check(guards,manifest['hosts'][host]['guard_ancestors'])
 return manifest,entries,guards

def install(package,host,apply=False):
 manifest,entries,guards=validate(package,host)
 units=UNITS[host];timers=[u.replace('.service','.timer') for u in units]
 if not all(state(t)=='active' for t in timers):raise ValueError('timer_baseline')
 if not all(state(u)=='inactive' for u in units):return {'result':'BUSY_NO_CHANGE','host':host}
 if not apply:return {'result':'PREFLIGHT_PASS_NO_CHANGE','host':host,'manifest_sha256':MANIFEST_SHA256}
 safe_parent(Path('/var/backups'))
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
 backup=Path('/var/backups')/('GO-SAME-REVISION-'+host+'-'+stamp)
 backup.mkdir(mode=0o700)
 sync(backup.parent)
 receipt={'schema':'go.same-revision.source-install.v1','host':host,'manifest_sha256':MANIFEST_SHA256,
          'backup':str(backup),'task_dispatched':False,'authority_changed':False,'business_runtime_changed':False}
 stopped=[];staged=[];replaced=[];restart_allowed=True
 try:
  for t in timers:run(['systemctl','stop',t]);stopped.append(t)
  if not all(state(u)=='inactive' for u in units):
   receipt['result']='BUSY_NO_CHANGE';return receipt
  validate(package,host) # Recheck immutable source and authority after quiescing.
  for i,e in enumerate(entries):
   p=Path(e['target']);q=p.with_name(p.name+'.same-revision-'+stamp)
   if e['before'].get('exists') is not False:
    write_new(backup/(str(i)+'.before'),p.read_bytes(),e['before'])
    if info(backup/(str(i)+'.before'))!=e['before']:raise ValueError('backup_identity')
   staged.append(q)
   write_new(q,package['files'][e['source']].encode(),after_info(e))
  write_new(backup/'BACKUP_MANIFEST.json',canonical({'host':host,'manifest':manifest}),{'uid':0,'gid':0,'mode':0o600})
  sync(backup) # Complete recoverable before-images precede the first replacement.
  for e,q in zip(entries,staged):
   restart_allowed=False
   p=Path(e['target']);os.replace(q,p);replaced.append(e);sync(p.parent)
  receipt['smoke']=run(['python3','-B','-c',SMOKE[host]]).stdout.strip()
  for e in entries:
   if info(e['target'])!=after_info(e):raise ValueError('installed_identity')
  guard_check(guards,manifest['hosts'][host]['guard_ancestors'])
  receipt['after']={e['target']:info(e['target']) for e in entries}
  restart_allowed=True
  receipt['result']='SOURCE_INSTALLED_NO_ADMISSION_OR_DEPLOY'
 except BaseException as exc:
  restore_errors=[]
  for e in reversed(replaced):
   try:
    p=Path(e['target']);i=entries.index(e)
    if e['before'].get('exists') is False:p.unlink()
    else:
     raw=(backup/(str(i)+'.before')).read_bytes()
     if digest(raw)!=e['before']['sha256']:raise ValueError('restore_backup_hash')
     q=p.with_name(p.name+'.restore-'+stamp);staged.append(q)
     write_new(q,raw,e['before']);os.replace(q,p)
    sync(p.parent)
    if info(p)!=e['before']:raise ValueError('restore_identity')
   except BaseException as restore_exc:
    restore_errors.append({'target':e['target'],'error':type(restore_exc).__name__+': '+str(restore_exc)})
  try:
   restart_allowed=(not restore_errors and all(info(e['target'])==e['before'] for e in entries)
                    and guard_check(guards,manifest['hosts'][host]['guard_ancestors']))
  except BaseException:
   restart_allowed=False
  receipt['restore_errors']=restore_errors
  receipt['result']=('SOURCE_RESTORED' if replaced else 'NOT_INSTALLED') if restart_allowed else 'RECONCILIATION_REQUIRED'
  receipt['error']=type(exc).__name__+': '+str(exc)
  raise
 finally:
  cleanup_errors=[]
  for q in staged:
   try:
    if q.exists():q.unlink()
   except BaseException as cleanup_exc:
    cleanup_errors.append({'path':str(q),'error':type(cleanup_exc).__name__})
  restart_errors=[]
  if restart_allowed:
   for t in stopped:
    try:run(['systemctl','start',t])
    except BaseException as exc:restart_errors.append({'timer':t,'error':type(exc).__name__})
  receipt['timer_after']={t:state(t) for t in timers}
  receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  receipt['timer_restart_errors']=restart_errors
  receipt['cleanup_errors']=cleanup_errors
  receipt['timers_intentionally_held']=not restart_allowed
  write_new(backup/'receipt.json',(json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode(),{'uid':0,'gid':0,'mode':0o600})
  sync(backup)
  print(json.dumps(receipt,sort_keys=True))
  if restart_errors:raise ValueError('timer_restore_requires_reconciliation')
 return receipt

def main():
 if os.geteuid()!=0:raise ValueError('root_required')
 if len(sys.argv)!=3 or sys.argv[1] not in TARGETS or sys.argv[2] not in ('--check','--apply'):raise ValueError('arguments')
 if socket.gethostname()!={'go-cc':'iZj6c7k6k01biwlbnwutu5Z','hk-staging':'iZj6ccs8t04f1p4d8pe69zZ'}[sys.argv[1]]:raise ValueError('hostname_mismatch')
 package=json.load(sys.stdin)
 if sys.argv[2]=='--check':
  print(json.dumps(install(package,sys.argv[1],False),sort_keys=True));return
 # Serialize installers only; the normal Agent/Bridge locks are never modified.
 path=Path('/var/backups/go-same-revision-install.lock');safe_parent(path.parent)
 fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o077:raise ValueError('installer_lock_owner')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  print(json.dumps(install(package,sys.argv[1],True),sort_keys=True))
 finally:os.close(fd)

if __name__=='__main__':main()
