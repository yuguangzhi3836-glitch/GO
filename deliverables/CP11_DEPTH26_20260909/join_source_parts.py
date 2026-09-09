"""Join the reviewed source archive and verify each part plus the final SHA256."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/'SOURCE_PARTS.json').read_text())
name=manifest['archive']
assert Path(name).name==name and name.endswith('.zip')
chunks=[]
for i,row in enumerate(manifest['parts'],1):
    assert row['path']==name+f'.part{i:02d}'
    data=(root/row['path']).read_bytes()
    assert len(data)==row['size'] and hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
    chunks.append(data)
data=b''.join(chunks)
assert len(data)==manifest['size'] and hashlib.sha256(data).hexdigest()==manifest['sha256']
target=root/name
if target.exists():
    assert hashlib.sha256(target.read_bytes()).hexdigest()==manifest['sha256'],'EXISTING_ARCHIVE_DIFFERS'
else:
    with target.open('xb') as f:f.write(data)
print(name+' SHA256 '+manifest['sha256']+' VERIFIED')
