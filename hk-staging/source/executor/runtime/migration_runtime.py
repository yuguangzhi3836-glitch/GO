"""Forward-only migration before image cutover, with durable uncertainty fencing."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

STATE=Path('/var/lib/go-hk-deployctl/migrations-v1')
TRUSTED_UID=0
PROGRAM_SHA256='526ace4129c76dfaa942afeb6dffa43d7b52227308005645fe4dad1ce1fac1de'

class Reject(ValueError):
    pass

def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':')).encode()

def program():
    path=Path(__file__).with_name('migration_program.py')
    if not stat.S_ISREG(path.lstat().st_mode): raise Reject('E_MIGRATION_PROGRAM_TYPE')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PROGRAM_SHA256: raise Reject('E_MIGRATION_PROGRAM_HASH')
    return raw.decode()+'\nentry()\n'

def spec(contract):
    return {'baseline_revision':contract['baseline_revision'],'target_revision':contract['target_revision'],
            'lineage_sha256':contract['rehearsal']['migration_source_digest']}

def source_tail(contract):
    return ['-c',program(),'source',canonical(spec(contract)).decode()]

def atomic_new(path,value):
    raw=canonical(value)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
    with os.fdopen(fd,'wb') as handle:
        handle.write(raw);handle.flush();os.fsync(handle.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return hashlib.sha256(raw).hexdigest()

def prepare(contract,identity,binding,deploy_record,state=STATE):
    state=Path(state);state.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=TRUSTED_UID or info.st_mode&0o077:
        raise Reject('E_MIGRATION_STATE_OWNER')
    # One fixed unresolved intent for the environment. Changing Task/nonce or
    # candidate cannot turn an uncertain previous attempt into a fresh attempt.
    pending=state/'pending.json'
    if pending.exists() or pending.is_symlink(): raise Reject('E_MIGRATION_UNRESOLVED_ATTEMPT')
    record={'schema':'go.hk-forward-migration-intent.v1','environment':'HK-STAGING-01',
            'contract_sha256':identity,'task_binding':dict(binding),
            'deploy_record_id':deploy_record['deploy_record_id'],
            'candidate_image_id':contract['candidate']['image_id'],
            'baseline_revision':contract['baseline_revision'],'target_revision':contract['target_revision'],
            'automatic_retry_allowed':False}
    try: digest=atomic_new(pending,record)
    except FileExistsError as exc: raise Reject('E_MIGRATION_UNRESOLVED_ATTEMPT') from exc
    return {'intent':record,'intent_sha256':digest,'path':str(pending)}

def execute(contract,identity,binding,deploy_record,runner,deploy,override,state=STATE):
    intent=prepare(contract,identity,binding,deploy_record,state)
    name='go-hk-migration-'+deploy_record['deploy_record_id'][:24]
    argv=[deploy.DOCKER,'compose','--env-file',deploy.ENV,'-p',deploy.PROJECT,
          '-f',deploy.COMPOSE,'-f',override,'run','--no-deps','-T','--name',name,
          '--workdir','/workspace','--entrypoint','/usr/local/bin/python','api',
          '-c',program(),'migrate',canonical(spec(contract)).decode()]
    try:
        result=runner.run(argv)
        if result.returncode: raise Reject('E_MIGRATION_EXECUTION_FAILED')
        try: outcome=json.loads(result.stdout)
        except (ValueError,TypeError) as exc: raise Reject('E_MIGRATION_OUTPUT') from exc
        expected={'source':'PASS','lineage_sha256':contract['rehearsal']['migration_source_digest'],
                  'prestate':contract['baseline_revision'],'poststate':contract['target_revision']}
        if outcome!=expected: raise Reject('E_MIGRATION_POSTSTATE')
        receipt={'schema':'go.hk-forward-migration-receipt.v1','intent_sha256':intent['intent_sha256'],
                 'contract_sha256':identity,'task_binding':dict(binding),'result':outcome}
        receipt_path=Path(state)/(deploy_record['deploy_record_id']+'.json')
        digest=atomic_new(receipt_path,receipt)
        return {**intent,'receipt_sha256':digest}
    finally:
        # Explicit cleanup covers timeout too. The pending intent remains until
        # the entire cutover and post-VERIFY succeed, never merely on SQL exit 0.
        cleaned=runner.run([deploy.DOCKER,'rm','-f',name])
        if cleaned.returncode: raise Reject('E_MIGRATION_CLEANUP')

def complete(receipt):
    path=Path(receipt['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['intent_sha256']:
        raise Reject('E_MIGRATION_INTENT_CHANGED')
    # Keep the immutable intent as well as the receipt. An uncertain failure
    # before this rename remains fenced and requires explicit reconciliation.
    final=path.with_name(receipt['intent']['deploy_record_id']+'.intent.json')
    os.link(path,final);path.unlink()
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def require_clear(state=STATE):
    p=Path(state)/'pending.json'
    if p.exists() or p.is_symlink(): raise Reject('E_MIGRATION_UNRESOLVED_ATTEMPT')
