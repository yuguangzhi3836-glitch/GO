"""Install fixed, verified candidate facts; no deployment plan or Task is created."""
import base64, datetime, hashlib, json, os, pathlib, shutil, stat, subprocess, sys
from cryptography.hazmat.primitives import serialization

PACKAGE_SHA256 = '990c30dd431836e30291aa6fbe336d0186c5370711d4abd922f73dff26055ddb'
CONTRACT_SHA256 = '23d78ea846b21ace5318335eacb2a75826db5ff56cd925c8f8c58f6a83babed6'
OLD_VERIFY_SHA256 = '76bab57106fc19e677ac1f2c66f25d37cedc93525dc655ab1d7fe4076460ab4f'
LIVE_IMAGE = 'sha256:6b92050ed42c115d29d2ff0b540c711b21747c7ed961384629a35571cf6b93a7'
SERVICES = {'api','recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker'}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def run(argv,check=True):return subprocess.run(argv,capture_output=True,text=True,check=check,timeout=45)
def state(unit):return run(['systemctl','is-active',unit],False).stdout.strip()
def safe(path):
    for p in [path,*path.parents]:
        s=p.lstat();assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,str(p)
def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def verify_pair(package,task_name,evidence_name):
    task=json.loads(package[task_name]);evidence=json.loads(package[evidence_name])
    for role,obj in [('TASK',task),('EVIDENCE',evidence)]:
        keyraw=package[role+'_PUBLIC_KEY'].encode()
        assert digest(keyraw)==package['identities'][role]['public_key_file_sha256']
        key=serialization.load_ssh_public_key(keyraw)
        assert digest(key.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))==package['identities'][role]['public_key_raw_sha256']
        sig=bytes.fromhex(obj['signature']) if role=='TASK' else base64.b64decode(obj['signature'],validate=True)
        key.verify(sig,canonical({k:v for k,v in obj.items() if k!='signature'}))
    for field in ['task_id','nonce','action_id','environment']:assert task[field]==evidence[field]
    assert evidence['status']=='SUCCESS' and evidence['environment']=='HK-STAGING-01'
    return task,evidence

def main():
    assert os.geteuid()==0
    package=json.load(sys.stdin);assert digest(canonical(package))==PACKAGE_SHA256
    host=sys.argv[1];assert host in ['go-cc','hk-staging']
    current_task,current=verify_pair(package,'CURRENT_VERIFY_TASK','CURRENT_VERIFY_EVIDENCE')
    test_task,test=verify_pair(package,'TEST_PR_TASK','TEST_PR_EVIDENCE')
    assert current['executor_result']=='VERIFY_OK' and current['candidate_image_id']==LIVE_IMAGE
    assert current_task['parameters']['expected_current_image_id']==LIVE_IMAGE
    assert current_task['issued_at']<current['completed_at']<current_task['expires_at']
    assert test['executor_result']=='TEST_PR_OK' and test['source_commit_sha']=='edd3500575d2f2b81298cc9273025e0a3b734897'
    contract=json.loads(package['CANDIDATE_CONTRACT']);assert digest(canonical(contract))==CONTRACT_SHA256
    assert contract['expected_current_image_id']==LIVE_IMAGE
    assert digest(package['TEST_PR_EVIDENCE'].encode())==contract['rehearsal']['binding']['test_pr_evidence_sha256']
    assert test['built_image_id']==contract['candidate']['image_id']
    assert test['artifact_package']['package_sha256']==contract['candidate']['package_sha256']
    module_dir='/usr/local/libexec' if host=='go-cc' else '/usr/local/libexec/go-hk-deployctl-runtime'
    module_path=pathlib.Path(module_dir)/'hk_candidate_contract.py';safe(module_path.parent)
    module_stat=module_path.lstat()
    assert stat.S_ISREG(module_stat.st_mode) and module_stat.st_uid==0 and not module_stat.st_mode&0o022
    assert digest(module_path.read_bytes())=='0d30f5b76da072a249f9c1986d71fe09664d31bda06d4c944e684e2f1746e3ed'
    sys.path.insert(0,module_dir);import hk_candidate_contract
    assert pathlib.Path(hk_candidate_contract.__file__)==module_path
    hk_candidate_contract.validate(contract,CONTRACT_SHA256)
    units=['go-boss-request-bridge.service'] if host=='go-cc' else ['go-hk-agent.service']
    timers=[u.replace('.service','.timer') for u in units]
    store=hk_candidate_contract.CC_STORE if host=='go-cc' else hk_candidate_contract.HK_STORE
    targets=[(store/(CONTRACT_SHA256+'.json'),package['CANDIDATE_CONTRACT'].encode(),None)]
    if host=='go-cc':
        targets += [(pathlib.Path('/etc/go-command-center/boss-request-verify-baseline-v1.json'),package['VERIFY_BASELINE'].encode(),OLD_VERIFY_SHA256),
                    (hk_candidate_contract.CC_ACTIVE,package['ACTIVE_CANDIDATE'].encode(),None)]
    else:
        ids=run(['docker','ps','-q','--filter','label=com.docker.compose.project=go-822-staging']).stdout.split()
        seen={}
        for cid in ids:
            d=json.loads(run(['docker','inspect',cid]).stdout)[0];name=d['Config']['Labels']['com.docker.compose.service']
            if name in SERVICES:assert name not in seen;seen[name]=d['Image']
        assert set(seen)==SERVICES and set(seen.values())=={LIVE_IMAGE},'live image drift'
    for p,raw,old in targets:
        if old is None:assert not p.exists() and not p.is_symlink(),'target exists'
        else:
            s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and not s.st_mode&0o077
            assert digest(p.read_bytes())==old,'baseline moved'
    assert all(state(t)=='active' for t in timers)
    if not all(state(u)=='inactive' for u in units):print(json.dumps({'result':'BUSY_NO_CHANGE','host':host}));return
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=pathlib.Path('/var/backups')/('GO-ADMISSION-'+stamp+'-issue103-'+host);backup.mkdir(mode=0o700)
    receipt={'schema':'go.issue103.admission-install.v1','host':host,'contract_sha256':CONTRACT_SHA256,
             'package_sha256':PACKAGE_SHA256,'backup':str(backup),'task_dispatched':False,'deployment_performed':False,
             'current_signed_verify_sha256':digest(package['CURRENT_VERIFY_EVIDENCE'].encode()),'fresh_verify_still_required':True}
    stopped=[];created=[];written=[]
    try:
        for t in timers:run(['systemctl','stop',t]);stopped.append(t)
        if not all(state(u)=='inactive' for u in units):receipt['result']='BUSY_NO_CHANGE';return
        for directory in [store.parent,store]:
            if not directory.exists():safe(directory.parent);directory.mkdir(mode=0o755);created.append(directory)
            safe(directory)
        for p,raw,old in targets:
            safe(p.parent)
            if old is None:assert not p.exists() and not p.is_symlink()
            else:
                assert digest(p.read_bytes())==old;shutil.copy2(p,backup/(p.name+'.before'))
            q=p.with_name(p.name+'.issue103-'+stamp)
            with q.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            os.chown(q,0,0);os.chmod(q,0o600);os.replace(q,p);written.append((p,old));sync(p.parent)
        assert hk_candidate_contract.load(CONTRACT_SHA256,store)==contract
        if host=='go-cc':
            assert hk_candidate_contract.active()[1]==contract
            import runpy
            bridge=runpy.run_path('/usr/local/libexec/go-boss-request-bridge',run_name='admission_check')
            assert bridge['load_baseline']()['image_id']==LIVE_IMAGE
            assert bridge['load_canary_baseline']()['candidate_contract_sha256']==CONTRACT_SHA256
        receipt['files']={str(p):digest(p.read_bytes()) for p,_,_ in targets};receipt['result']='ADMITTED_FACTS_ONLY'
    except BaseException as exc:
        for p,old in reversed(written):
            if old is None:p.unlink()
            else:
                q=p.with_name(p.name+'.restore-'+stamp);shutil.copy2(backup/(p.name+'.before'),q);os.replace(q,p)
            sync(p.parent)
        for p in reversed(created):p.rmdir()
        receipt['result']='ADMISSION_RESTORED';receipt['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        for t in stopped:run(['systemctl','start',t])
        receipt['timer_after']={t:state(t) for t in timers};receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (backup/'receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n');print(json.dumps(receipt,sort_keys=True))

if __name__=='__main__':main()
