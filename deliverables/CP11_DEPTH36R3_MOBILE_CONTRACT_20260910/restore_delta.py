"""Restore a reviewed delta only onto its exact fingerprinted parent tree."""
import argparse,base64,hashlib,json,shutil
from pathlib import Path,PurePosixPath
p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sha=lambda b:hashlib.sha256(b).hexdigest()
def safe(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or str(p)!=name:raise ValueError('UNSAFE_PATH')
    return p
def fingerprint(path):return json.loads(path.read_text())
def verify(root,fp):
    for name,h in fp.items():
        p=root/safe(name)
        if p.is_symlink() or sha(p.read_bytes())!=h:raise ValueError('SOURCE_MISMATCH:'+name)
parent=fingerprint(a.package/'PARENT_FINGERPRINT.json');target=fingerprint(a.package/'SOURCE_FINGERPRINT.json')
meta=fingerprint(a.package/'MANIFEST.json');delta=fingerprint(a.package/'DELTA.json')
tree=lambda fp:sha(''.join(f'{k}\0{v}\n' for k,v in sorted(fp.items())).encode())
assert tree(parent)==meta['parent_source_tree_sha256']
assert tree(target)==meta['source_tree_sha256']
assert sha((a.package/'DELTA.json').read_bytes())==meta['delta_sha256']
verify(a.parent,parent)
if a.output.exists():raise ValueError('NEW_OUTPUT_REQUIRED')
assert set(delta)=={k for k in target if parent.get(k)!=target[k]}
assert set(parent)<=set(target), 'No deletions in this candidate'
a.output.mkdir(parents=True)
for name in parent:
    dest=a.output/safe(name);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.parent/name,dest)
for name,encoded in delta.items():
    raw=base64.b64decode(encoded,validate=True)
    assert sha(raw)==target[name],name
    dest=a.output/safe(name);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
verify(a.output,target)
print(json.dumps({'verified_files':len(target),'source_tree_sha256':tree(target),'parent_verified_files':len(parent),'changed_files':len(delta),'environment':'offline restoration only','release_gate':'HOLD'}))
