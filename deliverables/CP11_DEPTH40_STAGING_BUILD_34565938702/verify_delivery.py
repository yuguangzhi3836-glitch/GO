"""Read-only delivery verification; no Docker command, extraction, load or deployment."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

ap=argparse.ArgumentParser();ap.add_argument('--directory',type=Path,required=True);a=ap.parse_args()
root=a.directory.resolve();sha=lambda b:hashlib.sha256(b).hexdigest()
expected={}
for line in (root/'SHA256SUMS').read_text().splitlines():
    digest,name=line.split('  ',1)
    p=root/name
    if name in expected or p.is_symlink() or root not in p.resolve().parents:
        raise ValueError('UNSAFE_OR_DUPLICATE_MEMBER')
    if sha(p.read_bytes())!=digest:raise ValueError('FILE_SHA_MISMATCH:'+name)
    expected[name]=digest
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
if actual!=set(expected)|{'SHA256SUMS'}:raise ValueError('FILE_SET_MISMATCH')
meta=json.loads((root/'RUNTIME_MANIFEST.json').read_text())
parts=json.loads((root/'RUNTIME_PARTS.json').read_text());chunks=[]
for i,part in enumerate(parts['parts']):
    if part['name']!=parts['archive_name']+f'.part{i:03}':raise ValueError('PART_ORDER')
    b=(root/part['name']).read_bytes()
    if len(b)!=part['size'] or sha(b)!=part['sha256']:raise ValueError('PART_SHA')
    chunks.append(b)
raw=b''.join(chunks)
if len(raw)!=parts['size'] or sha(raw)!=parts['archive_sha256'] or sha(raw)!=meta['runtime_archive_sha256']:
    raise ValueError('IMAGE_ARCHIVE_SHA')
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as t:
    manifest=json.load(t.extractfile('manifest.json'))
    if len(manifest)!=1:raise ValueError('ONE_IMAGE_REQUIRED')
    config=t.extractfile(manifest[0]['Config']).read()
    if 'sha256:'+sha(config)!=meta['image_config_id']:raise ValueError('IMAGE_CONFIG_SHA')
print(json.dumps({'status':'PASS_INTEGRITY_ONLY','verified_files':len(expected),
    'parts':len(parts['parts']),'runtime_archive_sha256':sha(raw),'image_config_id':meta['image_config_id'],
    'runtime_gate':meta['isolated_pg16_eight_service_gate'],'hk_execution':'NOT_RUN'}))
