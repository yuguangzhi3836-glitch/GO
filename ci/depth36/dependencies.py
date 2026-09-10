"""Extract only the repository's frozen wheels. Never restore historical app code."""
import argparse,hashlib,io,json,stat,zipfile
from pathlib import Path,PurePosixPath
p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():raise ValueError('NEW_DEPENDENCY_DIRECTORY_REQUIRED')
sha=lambda b:hashlib.sha256(b).hexdigest()
meta=json.loads((a.repository/'ci/DEPENDENCIES.json').read_text())
parts=[]
for part in meta['parts']:
 if Path(part['name']).name!=part['name']:raise ValueError('UNSAFE_PART')
 data=(a.repository/'ci/dependency_parts'/part['name']).read_bytes()
 if len(data)!=part['size'] or sha(data)!=part['sha256']:raise ValueError('PART_INTEGRITY')
 parts.append(data)
raw=b''.join(parts)
if sha(raw)!='b13a76ab9351f81da70e8e2c8873c20141abe953cd3f96aeb181ef86a34b58dd':raise ValueError('FROZEN_WHEELS_INTEGRITY')
with zipfile.ZipFile(io.BytesIO(raw)) as z:
 if len(z.namelist())!=len(set(z.namelist())):raise ValueError('DUPLICATE_MEMBER')
 for wheel in meta['wheels']:
  name=wheel['path'];path=PurePosixPath(name)
  if path.is_absolute() or '..' in path.parts or '\\' in name or not name.startswith('wheelhouse/') or not name.endswith('.whl'):raise ValueError('UNSAFE_WHEEL')
  if stat.S_ISLNK(z.getinfo(name).external_attr>>16):raise ValueError('SYMLINK_WHEEL')
  data=z.read(name)
  if sha(data)!=wheel['sha256']:raise ValueError('WHEEL_INTEGRITY')
  target=a.output/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
print(json.dumps({'archive_sha256':sha(raw),'verified_wheels':len(meta['wheels']),'source':'pinned GO repository ci/dependency_parts only','application_source_restored':False}))
