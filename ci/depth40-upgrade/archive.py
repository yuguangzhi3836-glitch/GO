"""Persist only this synthetic experiment to a new branch in the user's private GO repo."""
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request,urlopen

repo='yuguangzhi3836-glitch/GO'
run=os.environ['GITHUB_RUN_ID']; assert run.isdigit()
branch='evidence/depth40-upgrade-recovery-'+run
prefix='evidence/DEPTH40_UPGRADE_RECOVERY_'+run
root=Path('upgrade-evidence')
parent=os.environ['GO_REVIEW_HEAD']

def api(path,data=None):
    req=Request('https://api.github.com/repos/'+repo+'/'+path,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization':'Bearer '+os.environ['GO_ARCHIVE_TOKEN'],
                 'Accept':'application/vnd.github+json','Content-Type':'application/json'})
    with urlopen(req,timeout=90) as response:return json.load(response)

assert api('')['private'] is True
elements=[]
expected={}
for line in (root/'SHA256SUMS').read_text().splitlines():
    sha,name=line.split('  ',1); expected[name]=sha
files={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
assert files==set(expected)|{'SHA256SUMS'}
for name in sorted(files):
    p=root/name; assert not p.is_symlink() and '..' not in p.parts
    assert p.suffix in {'.json','.log','.md','.py','.yml','.dump'} or name=='SHA256SUMS'
    if p.suffix=='.dump': assert name=='SYNTHETIC_ONLY_0114.dump'
    data=p.read_bytes(); assert len(data)<20*1024*1024
    if name in expected: assert hashlib.sha256(data).hexdigest()==expected[name]
    blob=api('git/blobs',{'content':base64.b64encode(data).decode(),'encoding':'base64'})
    assert blob['sha']==hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    elements.append({'path':prefix+'/'+name,'mode':'100644','type':'blob','sha':blob['sha']})
tree=api('git/trees',{'base_tree':api('git/commits/'+parent)['tree']['sha'],'tree':elements})
commit=api('git/commits',{'message':'evidence: DEPTH40 isolated PG18 upgrade and media recovery outcome',
    'tree':tree['sha'],'parents':[parent]})
api('git/refs',{'ref':'refs/heads/'+branch,'sha':commit['sha']})
assert api('git/ref/heads/'+branch)['object']['sha']==commit['sha']
print(json.dumps({'archive_commit':commit['sha'],'branch':branch,'prefix':prefix,
                  'hk_execution':'NOT_RUN'}))
