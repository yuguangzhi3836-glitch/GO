"""Seal incremental DEPTH26; restore from locked archives into a new directory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PREVIOUS='cad8423d6cfc9d77f4019d87b812688cca7c728c0806e34ff79ff288d92d91ee'
SOURCE25='925b4d00ec2abaea023b1ce23611cde1c2019b3ac701c86300eb5e3922d9b2d7'
COMMIT25='60486d516c1b7dbc00540b61406937e9fd0b8957'
EVIDENCE='verification/current_build/depth26'

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def dump(p,data):Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def load(p):return json.loads(Path(p).read_text())
def row(root,name):
    p=root/name
    assert p.is_file() and not p.is_symlink(),name
    return {'path':name,'size':p.stat().st_size,'sha256':sha(p)}

def write_zip(path,root,names,metadata):
    assert not path.exists(),'IMMUTABLE_OUTPUT_EXISTS'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name in sorted(names):z.write(root/name,name)
        for name,data in metadata.items():z.writestr(name,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(path) as z:assert z.testzip() is None

def seal(a):
    root=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    assert sha(a.previous_delta)==PREVIOUS and sha(a.previous_source)==SOURCE25
    with zipfile.ZipFile(a.previous_delta) as z:before={r['path']:r for r in json.loads(z.read('RESULT_FILE_MANIFEST.json'))['files']}
    frozen=load(root/EVIDENCE/'source_fingerprint.json')['files']
    for name,h in frozen.items():assert sha(root/name)==h,name
    status=load(root/EVIDENCE/'CURRENT_BUILD_STATUS.json')
    assert status['new_backend_runtime']['runtime_gate']=='PASS'
    assert status['affected_python']['failures']==status['frontend']['failures']==0
    names=set(before)|set(frozen)|{str(p.relative_to(root)) for p in (root/EVIDENCE).rglob('*') if p.is_file()}
    names.update(['GO_DEPTH26_START_HERE.md','CURRENT_DEPTH_CANDIDATE.json'])
    assert not any(any(part in {'node_modules','__pycache__','.preview','.env','.git'} for part in Path(n).parts) for n in names)
    result=[row(root,n) for n in sorted(names)];changed=[]
    for r in result:
        old=before.get(r['path'])
        if not old or old['sha256']!=r['sha256']:
            changed.append({**r,'before_sha256':old['sha256'] if old else None,'mode':0o644})
    manifest={'build':'DEPTH26','previous_delta_sha256':PREVIOUS,'previous_checkpoint_commit':COMMIT25,
              'FINAL_RELEASE_GATE':'HOLD','preseal':False,'removed':[],'files':changed}
    result_manifest={'build':'DEPTH26','FINAL_RELEASE_GATE':'HOLD','files':result}
    delta=out/'GO_CP11_DEPTH26_DELTA_20260909.zip'
    assert not delta.exists()
    with zipfile.ZipFile(delta,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for r in changed:z.write(root/r['path'],'payload/'+r['path'])
        z.writestr('DEPTH26_DELTA_MANIFEST.json',json.dumps(manifest,indent=2))
        z.writestr('RESULT_FILE_MANIFEST.json',json.dumps(result_manifest,indent=2))
    with zipfile.ZipFile(a.previous_source) as z:source_names=set(z.namelist())-{'SOURCE_FILE_MANIFEST.json'}
    source_names.update(frozen);source_names.update(['GO_DEPTH26_START_HERE.md',EVIDENCE+'/source_fingerprint.json',EVIDENCE+'/CURRENT_BUILD_STATUS.json'])
    source=out/'GO_CP11_DEPTH26_SOURCE_20260909.zip'
    write_zip(source,root,source_names,{'SOURCE_FILE_MANIFEST.json':{'files':[row(root,n) for n in sorted(source_names)]}})
    receipt={'build':'DEPTH26','source_files':len(source_names),'result_files':len(result),'changed_files':len(changed),'frozen_files':len(frozen),
             'archives':[row(out,p.name) for p in [delta,source]],'FINAL_RELEASE_GATE':'HOLD'}
    dump(out/'GO_DEPTH26_DELIVERY.json',receipt);print(json.dumps(receipt,indent=2))

def restore(a):
    assert sha(a.delta)==a.expected_delta_sha256 and sha(a.previous_delta)==PREVIOUS
    assert not a.output.exists(),'OUTPUT_MUST_BE_NEW'
    subprocess.run([sys.executable,str(ROOT/'scripts/restore_depth25_checkpoint.py'),'restore',
        '--validator-source',str(ROOT),'--parent',str(a.parent),'--base-work',str(a.base_work),
        '--delta',str(a.previous_delta),'--expected-delta-sha256',PREVIOUS,'--output',str(a.output)],check=True)
    sys.path.insert(0,str(ROOT/'scripts'))
    from assemble_depth24_review import preflight,extract,verify_entries
    root=a.output.resolve();before={r['path']:r for r in load(root/'DELIVERY_FILE_MANIFEST.json')['files']}
    with zipfile.ZipFile(a.delta) as z:
        preflight(z);change=json.loads(z.read('DEPTH26_DELTA_MANIFEST.json'));result=json.loads(z.read('RESULT_FILE_MANIFEST.json'))
        assert change['previous_delta_sha256']==PREVIOUS and change['previous_checkpoint_commit']==COMMIT25
        assert not change['preseal'] and not change['removed']
        assert set(z.namelist())=={'DEPTH26_DELTA_MANIFEST.json','RESULT_FILE_MANIFEST.json',*('payload/'+r['path'] for r in change['files'])}
        verify_entries(z,change['files'],'payload/')
        known={n:{k:r[k] for k in ('path','size','sha256')} for n,r in before.items()}
        for r in change['files']:
            old=known.get(r['path']);assert (old['sha256'] if old else None)==r['before_sha256'],r['path']
            known[r['path']]={k:r[k] for k in ('path','size','sha256')}
        assert known=={r['path']:r for r in result['files']} and len(known)==len(result['files'])
        extract(z,root,'payload/')
    for r in result['files']:assert row(root,r['path'])==r,r['path']
    frozen=load(root/EVIDENCE/'source_fingerprint.json')['files']
    for name,h in frozen.items():assert sha(root/name)==h,name
    dump(root/'DELIVERY_FILE_MANIFEST.json',result)
    receipt={'build':'DEPTH26','verified_files':len(result['files']),'verified_frozen_files':len(frozen),'delta_sha256':sha(a.delta),
             'parent_sha256':sha(a.parent),'base_work_sha256':sha(a.base_work),'previous_delta_sha256':PREVIOUS,
             'method':'Fresh extraction of locked parent + DEPTH17 WORK + DEPTH25 DELTA + DEPTH26 DELTA; every result file SHA256 checked',
             'FINAL_RELEASE_GATE':'HOLD'}
    dump(root/'DEPTH26_RESTORATION.json',receipt);print(json.dumps(receipt,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('seal')
    for name in ['source','previous-delta','previous-source','output']:s.add_argument('--'+name,type=Path,required=True)
    s.set_defaults(run=seal)
    r=sub.add_parser('restore')
    for name in ['parent','base-work','previous-delta','delta','output']:r.add_argument('--'+name,type=Path,required=True)
    r.add_argument('--expected-delta-sha256',required=True);r.set_defaults(run=restore)
    args=p.parse_args();args.run(args)
