"""Persist only this verified delivery to a brand-new branch in the selected GO repo."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

ap=argparse.ArgumentParser(); ap.add_argument('--directory',type=Path,required=True); ap.add_argument('--run-id',required=True)
a=ap.parse_args(); assert a.run_id.isdigit()
repo='yuguangzhi3836-glitch/GO'; prefix='deliverables/CP11_DEPTH40_ISOLATED_RUNTIME_'+a.run_id
branch='deliverables/depth40-isolated-runtime-'+a.run_id
def api(path, value=None):
 request=Request('https://api.github.com/repos/'+repo+'/'+path,
   data=None if value is None else json.dumps(value).encode(),
   headers={'Authorization':'Bearer '+os.environ['GO_ARCHIVE_TOKEN'], 'Accept':'application/vnd.github+json','Content-Type':'application/json'})
 with urlopen(request,timeout=120) as response: return json.load(response)
manifest=json.loads((a.directory/'RUNTIME_MANIFEST.json').read_text())
assert manifest['offline_save_load_and_boot']=='PASS_CI' and manifest['deployment_authorized'] is False
parent='cf378e692e502d9ea663ef1c02cd66fb7a98c4da'
base_tree=api('git/commits/'+parent)['tree']['sha']
elements=[]
for p in sorted(a.directory.rglob('*')):
 if not p.is_file(): continue
 assert not p.is_symlink()
 rel=p.relative_to(a.directory).as_posix()
 assert not any(x in rel for x in ('credentials.private', 'acceptance.db', 'runtime.env'))
 data=p.read_bytes()
 blob=api('git/blobs',{'content':base64.b64encode(data).decode(),'encoding':'base64'})
 expected=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
 assert blob['sha']==expected
 elements.append({'path':prefix+'/'+rel,'mode':'100644','type':'blob','sha':blob['sha']})
tree=api('git/trees',{'base_tree':base_tree,'tree':elements})
commit=api('git/commits',{'message':'archive: DEPTH40 isolated runtime review package; no deployment','tree':tree['sha'],'parents':[parent]})
# Creation only. Existing branches cannot be overwritten or force-updated.
api('git/refs',{'ref':'refs/heads/'+branch,'sha':commit['sha']})
assert api('git/ref/heads/'+branch)['object']['sha']==commit['sha']
print(json.dumps({'archive_commit':commit['sha'],'branch':branch,'path':prefix,'deployment_authorized':False}))
