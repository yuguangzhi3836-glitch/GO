"""Archive only isolated evidence, publish to an evidence branch, then stop self."""
from pathlib import Path
from datetime import datetime, timezone
import os, json, shutil, subprocess, time, zipfile, hashlib
ROOT=Path('/workspaces/GO')
NAME='literate-winner-vpqqjgwvpjprcp7gw'
BRANCH='evidence/codespaces-4vcpu-20260930'
BASE='6220ef6622819c5077f5b723d334501c71cd08a2'
status=ROOT/'codespaces-capacity-evidence/status.json'
started=datetime.strptime(json.loads(status.read_text())['started_utc'],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
archive=ROOT/'codespaces-four-vcpu.zip'
result={'evidence_branch':BRANCH,'published':False}
try:
    while not archive.exists() and time.time()<started+5520:
        time.sleep(15)
    if not archive.exists():
        result['error']='Experiment did not finish within bounded runtime; partial evidence only'
        # Snapshot is explicitly incomplete. Never label it accepted.
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('INCOMPLETE.json',json.dumps(result))
            for folder in [ROOT/'codespaces-capacity-evidence',ROOT/'four-vcpu-fixed-worktree/four-vcpu-qualification',ROOT/'four-vcpu-fixed-worktree/cpu-candidate-evidence']:
                if folder.exists():
                    for p in folder.rglob('*'):
                        if p.is_file():z.write(p,p.relative_to(ROOT))
    time.sleep(5)
    dest=Path('/tmp/go-four-vcpu-publish')
    subprocess.run(['git','worktree','add','-b',BRANCH,str(dest),BASE],cwd=ROOT,check=True,timeout=60)
    evidence=dest/'ci/four_vcpu/evidence/20260930-codespaces'
    evidence.mkdir(parents=True,exist_ok=False)
    shutil.copy2(archive,evidence/'raw.zip')
    shutil.copy2(status,evidence/'status.json')
    (evidence/'SHA256.json').write_text(json.dumps({'raw.zip':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2)+'\n')
    (evidence/'README.md').write_text('Isolated 4-vCPU Codespaces evidence. Original 2-vCPU gate remains FAIL. Raw results require independent readback; no capacity, C14, C13, merge or deployment approval is inferred.\n')
    subprocess.run(['git','add','ci/four_vcpu/evidence/20260930-codespaces'],cwd=dest,check=True,timeout=30)
    subprocess.run(['git','commit','-m','test: preserve isolated Codespaces four-vCPU raw evidence'],cwd=dest,check=True,timeout=30)
    subprocess.run(['git','push','origin','HEAD:refs/heads/'+BRANCH],cwd=dest,check=True,timeout=120)
    result['published']=True
    result['commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip()
except Exception as exc:
    result['error_type']=type(exc).__name__
finally:
    (ROOT/'codespaces-capacity-evidence/finalization.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    # Stopping retains the disk and evidence; do not delete the codespace.
    subprocess.run(['gh','api','-X','POST','/user/codespaces/'+NAME+'/stop'],cwd=ROOT,timeout=60,check=False)
