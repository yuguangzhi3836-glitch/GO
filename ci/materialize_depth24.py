"""Materialize the immutable source for CI; original full restoration is separate."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile


def digest(data):return hashlib.sha256(data).hexdigest()


def extract(z, out, prefix=''):
    seen=set()
    for info in z.infolist():
        name=info.filename
        p=PurePosixPath(name)
        if name in seen or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or stat.S_ISLNK(info.external_attr >> 16):
            raise RuntimeError('UNSAFE_ARCHIVE_ENTRY')
        seen.add(name)
        if not name.startswith(prefix) or info.is_dir():continue
        target=out/name[len(prefix):]
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(z.read(name))


work_root=Path('deliverables/CP11_DEPTH17_20260908/work_parts')
work=b''.join(p.read_bytes() for p in sorted(work_root.glob('*.part*')))
assert digest(work)=='1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79'
Path('work.zip').write_bytes(work)
delta=Path(os.environ['DEPTH24_DELTA_PATH'])
assert digest(delta.read_bytes())==os.environ['DEPTH24_DELTA_SHA256']
output=Path('source');assert not output.exists();output.mkdir()
with zipfile.ZipFile('work.zip') as base,zipfile.ZipFile(delta) as change:
    old=json.loads(base.read('DELIVERY_FILE_MANIFEST.json'))
    manifest=json.loads(change.read('DEPTH24_DELTA_MANIFEST.json'))
    result_bytes=change.read('RESULT_FILE_MANIFEST.json')
    assert digest(result_bytes)==manifest['result_manifest_sha256'] and not manifest['removed']
    known={f['path']:f for f in old['files']}
    for f in old['files']:assert digest(base.read(f['path']))==f['sha256']
    for f in manifest['files']:
        previous=known.get(f['path'])
        assert (previous['sha256'] if previous else None)==f['before_sha256']
        assert digest(change.read('payload/'+f['path']))==f['sha256']
        known[f['path']]={k:f[k] for k in ('path','size','sha256')}
    result=json.loads(result_bytes)
    expected={f['path']:{k:f[k] for k in ('path','size','sha256')} for f in result['files']}
    assert expected=={n:{k:f[k] for k in ('path','size','sha256')} for n,f in known.items()}
    extract(base,output);extract(change,output,'payload/')
for f in result['files']:
    data=(output/f['path']).read_bytes()
    assert len(data)==f['size'] and digest(data)==f['sha256'],f['path']
frozen=json.loads((output/'verification/current_build/depth24/source_fingerprint.json').read_text())['files']
for name,sha in frozen.items():assert digest((output/name).read_bytes())==sha,name
dep=json.loads(Path('ci/DEPENDENCIES.json').read_text())
payload=[]
for part in dep['parts']:
    data=Path('ci/dependency_parts',part['name']).read_bytes()
    assert len(data)==part['size'] and digest(data)==part['sha256']
    payload.append(data)
joined=b''.join(payload)
assert digest(joined)==dep['sha256']
Path('dependencies.zip').write_bytes(joined)
with zipfile.ZipFile('dependencies.zip') as z:extract(z,Path('dependencies'))
for wheel in dep['wheels']:
    assert digest(Path('dependencies',wheel['path']).read_bytes())==wheel['sha256']
Path('evidence').mkdir(exist_ok=True)
Path('evidence/source_materialization.json').write_text(json.dumps({
    'scope':'SOURCE_MATERIALIZATION_FOR_CI_NOT_FULL_PARENT_RESTORATION',
    'verified_files':len(result['files']),'frozen_source_files':len(frozen),
    'delta_sha256':digest(delta.read_bytes()),'dependency_archive_sha256':dep['sha256']},indent=2))
print('Immutable source and frozen dependency wheelhouse verified')
