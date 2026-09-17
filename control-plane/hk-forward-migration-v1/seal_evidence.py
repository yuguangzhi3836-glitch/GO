"""Archive only the scoped gate outputs; checksum manifest excludes itself."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

source=Path(sys.argv[1]);out=source/'hk-forward-proof';out.mkdir(exist_ok=True)
for name in ('cc-checks','state-checks','executor-proof'):
    directory=source/name
    if directory.is_dir():shutil.copytree(directory,out/name,dirs_exist_ok=True)
root=Path(__file__).resolve().parents[2]
commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
tree=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD^{tree}'],text=True).strip()
result={'schema':'go.hk-shared-migration-gate.v1','tooling_sha':commit,'tooling_tree':tree,
        'status':'PASS_SCOPED','live_deployment_performed':False,'live_database_touched':False,
        'inherited_cell_tests_rerun':False}
for directory,filename in (('cc-checks','summary.json'),('state-checks','summary.json'),('executor-proof','EVIDENCE.json')):
    path=out/directory/filename
    try:status=json.loads(path.read_text())['status']
    except Exception:status='MISSING'
    result[directory]=status
    if status not in ('PASS','PASS_SCOPED'):result['status']='FAIL'
(out/'GATE_EVIDENCE.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
manifest=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(out))+'\n'
                 for p in sorted(out.rglob('*')) if p.is_file() and p.name!='SHA256SUMS')
(out/'SHA256SUMS').write_text(manifest)
print(json.dumps(result,sort_keys=True))
print('GATE_EVIDENCE_SHA256='+hashlib.sha256((out/'GATE_EVIDENCE.json').read_bytes()).hexdigest())
if result['status']!='PASS_SCOPED':raise SystemExit(1)
