"""Collect immutable build records without converting blocked external gates into PASS."""
import base64,gzip,hashlib,io,json,shutil,tarfile
from pathlib import Path
root=Path(__file__).resolve().parent
out=root/'evidence-publication/deliverables/CP11_DEPTH37_ACCEPTANCE_20260910';out.mkdir(parents=True,exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
def dump(p,obj):p.write_text(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
state=json.loads((root/'NEXT_STATE.json').read_text())
runs=json.loads((root/'ACCEPTANCE_RUNS.json').read_text())
raw={}; summaries={}
for record in runs:
    label=record['label'];directory=root/record['directory']
    command_file=directory/'commands.json'
    summaries[label]=json.loads(command_file.read_text()) if command_file.exists() else []
    target=out/label;target.mkdir(exist_ok=True)
    for p in sorted(directory.iterdir()):
        if p.suffix not in {'.log','.json','.png','.xml'}:continue
        raw[label+'/'+p.name]=p.read_bytes()
        if p.suffix=='.json' and p.name not in {'mobile-package-lock.json','package-lock.json','node-files.json'}:shutil.copyfile(p,target/p.name)
    joblog=root/record['job_log'];raw[label+'/RAW_JOB.log.gz']=gzip.compress(joblog.read_bytes(),mtime=0)
    dump(target/'CI_BINDING.json',record)
for name in ['REMAINING_EXTERNAL_INPUTS.md','SOURCE_CHANGES.patch','local-node-replay-result.json','LOCAL_CHECKS.json','support-provenance.json','dependency-layout-verification.json']:
    shutil.copyfile(root/name,out/name)
dump(out/'RUNTIME_ARTIFACT.json',state['node_runtime'])
for package in sorted((root/'deliverables').glob('CP11_DEPTH37*')):
    for p in package.glob('*.json'):
        if p.name != 'DELTA.json':raw['candidate/'+package.name+'/'+p.name]=p.read_bytes()
# Preserve superseded fingerprints and manifests even when the active package was corrected.
for snapshot in ['candidate-payload.json','candidate-r2-payload.json','candidate-r2-correction-payload.json']:
    path=root/snapshot
    if path.exists():
        for entry in json.loads(path.read_text()):
            name=Path(entry['path']).name
            if name in {'MANIFEST.json','SOURCE_FINGERPRINT.json','RELEASE_GATE.json','README.md','PARSER_CORRECTION.json'}:
                raw['candidate-history/'+snapshot.removesuffix('.json')+'/'+name]=entry['content'].encode()
archive=out/'RAW_EVIDENCE.tar.gz'
with archive.open('wb') as file,gzip.GzipFile(fileobj=file,mode='wb',mtime=0) as zipped,tarfile.open(fileobj=zipped,mode='w') as tar:
    for name,data in sorted(raw.items()):
        item=tarfile.TarInfo(name);item.size=len(data);item.mtime=0;tar.addfile(item,io.BytesIO(data))
dump(out/'RAW_EVIDENCE_INVENTORY.json',{'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,'members':{k:{'bytes':len(v),'sha256':sha(v)} for k,v in sorted(raw.items())}})
dump(out/'ACCEPTANCE_RUNS.json',runs)
dump(out/'SOURCE_BINDING.json',{k:state[k] for k in ['candidate_commit','candidate_tree','source_tree_sha256','verified_files','ci_commit','ci_tree','candidate_branch','ci_branch','pr']})
print(json.dumps({'output':str(out),'raw_members':len(raw),'raw_archive_bytes':archive.stat().st_size,'raw_archive_sha256':sha(archive.read_bytes()),'runs':list(summaries)},indent=2))
