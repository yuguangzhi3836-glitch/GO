"""Bounded shared-source maintenance. Never dispatches a Task or runs migration."""
import datetime, hashlib, json, os, pathlib, shutil, stat, subprocess, sys

REPAIR_SHA = 'bc71a91bff31a092aae003e061622878b8ef4bf6'
MANIFEST_SHA256 = 'f750fa9733225f828e17e70c16dbdffaf8719426d78e9418af77cbdf448f7ea0'
HOSTS = {
    'hk-staging': {
        'units': ['go-hk-agent.service'],
        'timers': ['go-hk-agent.timer'],
        'new_dirs': {'/var/lib/go-hk-deployctl/migrations-v1': 0o700},
        'ledger': '/var/lib/go-hk-agent/ledger',
        'smoke': "import sys,runpy;sys.path.insert(0,'/opt/go-hk-agent-rebuilt');from hk_agent import transport,deployment_actions,execution_window;assert transport.VERSION=='0.5.8-migration-window';d=runpy.run_path('/usr/local/libexec/go-hk-deployctl',run_name='installation_integrity_check');assert d['VERSION']=='0.5.0-forward-migration';[d[n]() for n in ['_load_collector','_load_canary','_load_deploy','_load_rollback','_load_artifact','_migration']];print('IMPORT_AND_PIN_CHECK_PASS')"
    },
    'go-cc': {
        'units': ['go-boss-request-bridge.service','go-command-center-state-cycle.service'],
        'timers': ['go-boss-request-bridge.timer','go-command-center-state-cycle.timer'],
        'new_dirs': {},
        'ledger': '/var/lib/go-command-center/boss-request-bridge-v1',
        'smoke': "import sys,runpy;sys.path.insert(0,'/usr/local/libexec');import go_deploy_request,plan_derivation,hk_candidate_contract,execution_window;runpy.run_path('/usr/local/libexec/go-boss-request-bridge',run_name='installation_integrity_check');sys.path.insert(0,'/opt/go-command-center/state-publication-v1/projection');import state_projection;assert hk_candidate_contract.active() is None;print('IMPORT_AND_PIN_CHECK_PASS')"
    }
}

def digest(raw): return hashlib.sha256(raw).hexdigest()
def canonical(v): return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def run(argv, check=True):
    return subprocess.run(argv,capture_output=True,text=True,check=check,timeout=45)
def state(unit): return run(['systemctl','is-active',unit],False).stdout.strip()
def info(name):
    p=pathlib.Path(name)
    if not p.exists() and not p.is_symlink(): return {'exists':False}
    s=p.lstat();assert stat.S_ISREG(s.st_mode) and not p.is_symlink(),name
    return {'sha256':digest(p.read_bytes()),'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'regular':True}
def sync_dir(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
def safe_parent(p):
    for d in [p,*p.parents]:
        s=d.lstat();assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,str(d)
def runtime():
    return sorted(run(['docker','ps','--no-trunc','--format','{{.ID}}|{{.Image}}|{{.Names}}']).stdout.splitlines())

def main():
    assert os.geteuid()==0
    package=json.load(sys.stdin);manifest=package['manifest']
    assert digest(canonical(manifest))==MANIFEST_SHA256,'manifest pin'
    assert manifest['repair_sha']==REPAIR_SHA
    host=sys.argv[1];settings=HOSTS[host]
    entries=[x for x in manifest['files'] if x['host']==host]
    assert set(package['files'])=={x['source'] for x in manifest['files']}
    for e in entries:
        raw=package['files'][e['source']].encode();assert digest(raw)==e['sha256'],e['source']
        compile(raw,e['target'],'exec');safe_parent(pathlib.Path(e['target']).parent)
        assert info(e['target'])==e['before'],'live baseline moved: '+e['target']
    guards=manifest['guards'][host]
    assert {p:info(p) for p in guards}==guards,'protected baseline moved'
    assert all(state(t)=='active' for t in settings['timers']),'timer baseline'
    if not all(state(u)=='inactive' for u in settings['units']):
        print(json.dumps({'result':'BUSY_NO_CHANGE','host':host}));return
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=pathlib.Path('/var/backups')/('GO-CHANGE-'+stamp+'-issue103-'+host)
    backup.mkdir(mode=0o700)
    receipt={'schema':'go.issue103.source-install.v1','host':host,'repair_sha':REPAIR_SHA,
             'manifest_sha256':MANIFEST_SHA256,'backup':str(backup),'started_at':stamp,
             'task_dispatched':False,'database_touched':False,'deployment_performed':False}
    staged={};replaced=[];new_dirs=[];timers_stopped=[]
    def save():
        (backup/'receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    try:
        for t in settings['timers']:
            run(['systemctl','stop',t]);timers_stopped.append(t)
        if not all(state(u)=='inactive' for u in settings['units']):
            receipt['result']='BUSY_NO_CHANGE';return
        assert all(info(e['target'])==e['before'] for e in entries),'baseline race'
        assert {p:info(p) for p in guards}==guards,'protected baseline race'
        receipt['protected_before']=guards
        if host=='hk-staging':receipt['runtime_before']=runtime()
        shutil.copytree(settings['ledger'],backup/'ledger-before',symlinks=True)
        for n,e in enumerate(entries):
            p=pathlib.Path(e['target']);before=e['before']
            if before.get('exists') is not False:
                shutil.copy2(p,backup/(str(n)+'.before'))
                assert info(backup/(str(n)+'.before'))==before
            q=p.with_name(p.name+'.issue103-'+stamp)
            with q.open('xb') as f:
                f.write(package['files'][e['source']].encode());f.flush();os.fsync(f.fileno())
            os.chown(q,0,0);os.chmod(q,e['mode']);staged[e['target']]=q
        for name,mode in settings['new_dirs'].items():
            p=pathlib.Path(name);safe_parent(p.parent)
            assert not p.exists() and not p.is_symlink(),'new directory already exists'
            p.mkdir(mode=mode);new_dirs.append(p);sync_dir(p.parent)
        for e in entries:
            p=pathlib.Path(e['target']);os.replace(staged[e['target']],p);replaced.append(e);sync_dir(p.parent)
        receipt['smoke']=run(['python3','-B','-c',settings['smoke']]).stdout.strip()
        receipt['after']={e['target']:info(e['target']) for e in entries}
        assert all(receipt['after'][e['target']]['sha256']==e['sha256'] for e in entries)
        receipt['protected_after']={p:info(p) for p in guards}
        assert receipt['protected_after']==guards
        if host=='hk-staging':
            receipt['runtime_after']=runtime();assert receipt['runtime_before']==receipt['runtime_after'],'runtime changed'
        receipt['result']='INSTALLED'
    except BaseException as exc:
        for e in reversed(replaced):
            p=pathlib.Path(e['target']);n=entries.index(e)
            if e['before'].get('exists') is False:p.unlink()
            else:
                q=p.with_name(p.name+'.restore-'+stamp);shutil.copy2(backup/(str(n)+'.before'),q);os.replace(q,p)
            sync_dir(p.parent);assert info(p)==e['before']
        for p in reversed(new_dirs):p.rmdir()
        receipt['result']='SOURCE_RESTORED' if replaced else 'NOT_INSTALLED'
        receipt['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        for p in staged.values():
            if p.exists():p.unlink()
        for t in timers_stopped:run(['systemctl','start',t])
        receipt['timer_after']={t:state(t) for t in settings['timers']}
        receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
        print(json.dumps(receipt,sort_keys=True))

if __name__=='__main__':main()
