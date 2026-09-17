"""Complete the installation record for already-reviewed PR187 projector bytes.

No projector or signing/Task code is modified. The normal integrity comparison remains.
"""
import datetime,fcntl,hashlib,json,os,pathlib,stat,subprocess
ROOT=pathlib.Path('/opt/go-command-center/state-publication-v1')
OLD='b208b4a702720d156b3f3279f6cdc77e00f69e3590686a035e7b1d56c5f7124e'
REV='bc71a91bff31a092aae003e061622878b8ef4bf6'
EXPECTED={'state_projection.py':'b7897d85ba14529952ff0e394270bca68bbd714f492f3c7ab324b5d436f1ae2f','execution_window.py':'8b4213eea8ea29b838490d41b99070fc5726d8207812be10be872ab149f6ff3e'}
def digest(raw):return hashlib.sha256(raw).hexdigest()
def run(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=30).stdout.strip()
def check():
    for name,expected in EXPECTED.items():
        p=ROOT/'projection'/name;s=p.lstat()
        assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and not (s.st_mode & 0o022)
        assert digest(p.read_bytes())==expected
    p=ROOT/'installed.json';s=p.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and not (s.st_mode & 0o022)
    raw=p.read_bytes();assert digest(raw)==OLD
    doc=json.loads(raw);assert doc['execution_authority'] is False
    return p,s,raw,doc
check()
timer='go-command-center-state-cycle.timer'
assert run(['systemctl','is-active',timer])=='active'
service=subprocess.run(['systemctl','is-active','go-command-center-state-cycle.service'],capture_output=True,text=True).stdout.strip()
assert service in ('inactive','failed'),service
run(['systemctl','stop',timer])
try:
    with open('/var/lib/go-command-center/state-publication-v1/.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        p,s,raw,doc=check()
        now=datetime.datetime.now(datetime.timezone.utc)
        backup=pathlib.Path('/var/backups')/('CC-CHANGE-'+now.strftime('%Y%m%dT%H%M%SZ')+'-issue103-projector-record')
        backup.mkdir(mode=0o700)
        (backup/'installed.json.before').write_bytes(raw)
        doc['projector_revision']=REV
        doc['projector_sha256']=EXPECTED['state_projection.py']
        doc['projector_companion_sha256']=EXPECTED['execution_window.py']
        doc['projector_installation_record_completed_at']=now.isoformat()
        after=(json.dumps(doc,sort_keys=True,indent=2)+'\n').encode()
        temp=p.with_name('installed.json.issue103.tmp')
        with open(temp,'xb') as f:
            os.fchmod(f.fileno(),stat.S_IMODE(s.st_mode));os.fchown(f.fileno(),s.st_uid,s.st_gid)
            f.write(after);f.flush();os.fsync(f.fileno())
        os.replace(temp,p)
        fd=os.open(str(ROOT),os.O_RDONLY);os.fsync(fd);os.close(fd)
        assert p.read_bytes()==after
        receipt={'schema':'go.issue103.projector-installation-receipt.v1','status':'PASS','observed_at':now.isoformat(),
                 'before_sha256':OLD,'after_sha256':digest(after),'backup':str(backup),'source_revision':REV,
                 'reviewed_files':EXPECTED,'integrity_check_retained':True,'source_modified':False,'deployment_performed':False}
        (backup/'receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
finally:
    run(['systemctl','start',timer])
print(json.dumps(receipt,sort_keys=True))
