"""Seal real outcomes; include only generated synthetic evidence and reviewed tooling."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from identity import binding

root=Path('upgrade-evidence'); root.mkdir(exist_ok=True)
dest=root/'review-tooling'; dest.mkdir(exist_ok=True)
for p in sorted(Path(__file__).resolve().parent.iterdir()):
    if p.suffix in {'.py','.md'}: shutil.copyfile(p,dest/p.name)
workflow=Path('.github/workflows/depth40-upgrade-recovery.yml')
shutil.copyfile(workflow,dest/workflow.name)
result=json.loads((root/'RESULT.json').read_text()) if (root/'RESULT.json').is_file() else {'status':'HOLD_NOT_COMPLETED'}
(root/'SUPPLEMENT_MANIFEST.json').write_text(json.dumps({**binding(),
    'run_id':os.environ['GITHUB_RUN_ID'],'tooling_commit':os.environ['GO_REVIEW_HEAD'],
    'scope':'CI_PG18_4_SYNTHETIC_UPGRADE_AND_MEDIA_PRESERVATION', 'actual_result':result['status'],
    'hk_execution':'NOT_RUN','migration_authorized':False,'deployment_authorized':False,
    'signed_task':'NOT_CREATED','production_release':'HOLD'},indent=2)+'\n')
lines=[]
for p in sorted(root.rglob('*')):
    if not p.is_file() or p.name=='SHA256SUMS': continue
    assert not p.is_symlink() and 'private.env' not in str(p)
    lines.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix())
(root/'SHA256SUMS').write_text('\n'.join(lines)+'\n')
print(json.dumps({'actual_result':result['status'],'sealed_files':len(lines),'hk_execution':'NOT_RUN'}))
