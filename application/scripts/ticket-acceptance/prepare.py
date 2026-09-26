"""Create a disposable source snapshot with a content fingerprint, never deploy."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[3]
target=Path(sys.argv[1]).resolve();target.mkdir(exist_ok=False)
paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z','application'],cwd=root,text=True).split('\0')
fp={}
for rel in sorted(set(paths)):
    if not rel or '__pycache__' in rel or rel.startswith('application/var/'):continue
    p=root/rel
    if not p.is_file():continue
    name=rel.removeprefix('application/');dest=target/'application'/name
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest);fp[name]=hashlib.sha256(p.read_bytes()).hexdigest()
tree=hashlib.sha256(''.join(f'{p}\0{h}\n' for p,h in sorted(fp.items())).encode()).hexdigest()
(target/'fingerprint.json').write_text(json.dumps(fp,indent=2)+'\n')
(target/'binding.json').write_text(json.dumps({'source_tree_sha256':tree,'candidate':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=root))},indent=2)+'\n')
print(tree)
