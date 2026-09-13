import base64, json, os, socket, sqlite3, shutil, tempfile
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

VERSION='0.5.7-rebuilt'
ENVIRONMENT='HK-STAGING-01'
AUTHORITY='GO-COMMAND-CENTER'
ALLOWLIST=frozenset({'CONTROL_PLANE_HEALTH','HK_STAGING_CANARY','HK_STAGING_DEPLOY','HK_STAGING_VERIFY','HK_STAGING_ROLLBACK'})
TASK_FIELDS={'schema_version','task_id','environment','action_id','issued_at','expires_at','nonce','parameters','authority','signature'}
EVIDENCE_FIELDS={'schema_version','task_id','nonce','action_id','environment','status','started_at','finished_at','result','agent_version','signature'}
class Reject(Exception): pass

def canonical(obj):
    return json.dumps({k:v for k,v in obj.items() if k!='signature'},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
def sign(obj,key):
    out=dict(obj); out['signature']=base64.b64encode(key.sign(canonical(out))).decode('ascii'); return out
def verify(obj,key):
    try: key.verify(base64.b64decode(obj['signature'],validate=True),canonical(obj)); return True
    except Exception: return False
def verify_task(obj,key):
    signature=obj.get('signature')
    if not isinstance(signature,str) or len(signature)!=128 or signature != signature.lower(): return False
    try: raw=bytes.fromhex(signature)
    except ValueError: return False
    if len(raw)!=64: return False
    try: key.verify(raw,canonical(obj)); return True
    except Exception: return False

def iso_now(): return datetime.now(timezone.utc).isoformat()
def parse_time(value): return datetime.fromisoformat(value.replace('Z','+00:00'))
def init_ledger(path):
    c=sqlite3.connect(path); c.execute('create table if not exists nonce_ledger(nonce text primary key, task_id text not null, status text not null, created_at text not null)'); c.commit(); return c
def require_schema(m):
    if not TASK_FIELDS.issubset(m) or set(m)-TASK_FIELDS: raise Reject('schema')
    if not isinstance(m['parameters'],dict) or not all(isinstance(m[k],str) and m[k] for k in TASK_FIELDS-{'parameters'}): raise Reject('schema')
def health(repo_state=None):
    stat=os.statvfs('/'); disk=stat.f_bavail*stat.f_frsize
    mem='unknown'
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'): mem=int(line.split()[1])*1024
    except OSError: pass
    return {'agent_version':VERSION,'hostname':socket.gethostname(),'current_time':iso_now(),'disk_free_bytes':disk,'memory_available_bytes':mem,'tasks_repo_connectivity':bool(repo_state and repo_state.get('tasks')),'evidence_repo_connectivity':bool(repo_state and repo_state.get('evidence'))}
def dispatch(m,task_key,evidence_key,ledger,repo_state=None):
    started=iso_now()
    try:
        require_schema(m)
        if m['environment']!=ENVIRONMENT: raise Reject('environment')
        if m['authority']!=AUTHORITY: raise Reject('authority')
        if not verify_task(m,task_key): raise Reject('signature')
        if parse_time(m['expires_at'])<=datetime.now(timezone.utc): raise Reject('expiry')
        try: ledger.execute('insert into nonce_ledger values(?,?,?,?)',(m['nonce'],m['task_id'],'admitted',iso_now())); ledger.commit()
        except sqlite3.IntegrityError: raise Reject('nonce')
        if m['action_id'] not in ALLOWLIST: raise Reject('allowlist')
        result=health(repo_state)
        status='SUCCESS'
    except Reject as e:
        status='REJECTED'; result={'gate':str(e)}
    ev={'schema_version':'1','task_id':m.get('task_id','unknown'),'nonce':m.get('nonce','unknown'),'action_id':m.get('action_id','unknown'),'environment':m.get('environment','unknown'),'status':status,'started_at':started,'finished_at':iso_now(),'result':result,'agent_version':VERSION}
    return sign(ev,evidence_key)
def public_line(key): return base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode('ascii')
