"""Verify/reassemble delivery files only; never invoke Docker or any server."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

ap=argparse.ArgumentParser(); ap.add_argument('--directory',required=True,type=Path)
ap.add_argument('--reassemble',type=Path)
a=ap.parse_args(); root=a.directory.resolve()
def path(name):
 p=PurePosixPath(name)
 if p.is_absolute() or '..' in p.parts or str(p)!=name or '\\' in name: raise ValueError('UNSAFE_PATH')
 f=root/name
 if f.is_symlink() or any(q.is_symlink() for q in f.parents if q!=root.parent): raise ValueError('SYMLINK')
 return f
for line in (root/'SHA256SUMS').read_text().splitlines():
 digest,name=line.split('  ',1)
 if hashlib.sha256(path(name).read_bytes()).hexdigest()!=digest: raise ValueError('FILE_CHECKSUM:'+name)
meta=json.loads((root/'RUNTIME_PARTS.json').read_text())
full=hashlib.sha256(); total=0
for part in meta['parts']:
 data=path(part['name']).read_bytes()
 if len(data)!=part['size'] or hashlib.sha256(data).hexdigest()!=part['sha256']: raise ValueError('PART_CHECKSUM')
 full.update(data); total+=len(data)
if full.hexdigest()!=meta['archive_sha256'] or total!=meta['size']: raise ValueError('ARCHIVE_CHECKSUM')
if a.reassemble:
 with a.reassemble.open('xb') as output:
  for part in meta['parts']: output.write(path(part['name']).read_bytes())
print(json.dumps({'status':'PASS','archive_sha256':full.hexdigest(),'archive_bytes':total,'docker_or_hk_execution':False}))
