"""Bind new backend checks to exact reviewed bytes over the preserved DEPTH25 base."""
import hashlib,json
from pathlib import Path
sha=lambda b:hashlib.sha256(b).hexdigest()
manifest=json.loads(Path('ci/DEPTH26_OVERLAY.json').read_text())
for row in manifest['files']:
    target=Path('source')/row['path']
    assert (sha(target.read_bytes()) if target.exists() else None)==row['before_sha256'],row['path']
    data=Path(row['source']).read_bytes();assert sha(data)==row['sha256']
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
Path('evidence/depth26_source_overlay.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Verified seven DEPTH26 backend files against DEPTH25 and reviewed SHA256.')
