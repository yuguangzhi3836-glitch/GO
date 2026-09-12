#!/usr/bin/env python3
"""Seal a verified DEPTH18 delta against the GitHub-pinned DEPTH17 cumulative WORK."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from build_review_delivery import allowed, digest

ROOT=Path(__file__).resolve().parents[1]
BASE_SHA='1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79'
PARENT_SHA='8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb'
STEM='GO_CP11_DEPTH_18_MEDIA_REGIONAL_DURABILITY'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-work',required=True,type=Path)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'deliverables')
    args=parser.parse_args();out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    if digest(args.baseline_work)!=BASE_SHA:parser.error('DEPTH17 WORK fingerprint mismatch')
    evidence=ROOT/'verification/current_build/depth18'
    status=json.loads((evidence/'CURRENT_BUILD_STATUS.json').read_text())
    assert status['python']['one_clean_full_run'] and not status['python']['failures'] and not status['python']['errors']
    frozen=json.loads((evidence/'full_run_source_fingerprint.json').read_text())['files']
    assert all(digest(ROOT/n)==h for n,h in frozen.items()),'FROZEN_SOURCE_CHANGED'
    with zipfile.ZipFile(args.baseline_work) as base:
        before={f['path']:f for f in json.loads(base.read('DELIVERY_FILE_MANIFEST.json'))['files']}
    names=set(before)
    for folder in ('src','frontend','tests','tests_frontend','scripts','acceptance','alembic'):
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*') if allowed(p))
    names.update(p.relative_to(ROOT).as_posix() for p in evidence.rglob('*') if allowed(p) and p.suffix!='.log')
    names.update({'GO_DEPTH18_START_HERE.md','CURRENT_DEPTH_CANDIDATE.json'})
    names.discard('DELIVERY_FILE_MANIFEST.json')
    result={'status':'ENGINEERING_REVIEW_NOT_RELEASE_ACCEPTED','files':[]}
    changes=[]
    for name in sorted(names):
        p=ROOT/name
        assert allowed(p),name
        row={'path':name,'size':p.stat().st_size,'sha256':digest(p)}
        result['files'].append(row)
        previous=before.get(name)
        if not previous or previous['sha256']!=row['sha256']:
            changes.append({**row,'before_sha256':previous['sha256'] if previous else None,'mode':p.stat().st_mode&0o777})
    result_bytes=json.dumps(result,ensure_ascii=False,indent=2).encode()
    manifest={'build':status['build'],'parent_sha256':PARENT_SHA,'baseline_work_sha256':BASE_SHA,
              'baseline_github_commit':'b02f65db7c6ce4212e3a4d678b540fb286c14768',
              'result_manifest_sha256':hashlib.sha256(result_bytes).hexdigest(),
              'FINAL_RELEASE_GATE':'HOLD','removed':[],'files':changes}
    path=out/(STEM+'_DELTA_20260908.zip');temporary=path.with_suffix('.building')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in changes:z.write(ROOT/f['path'],'payload/'+f['path'])
        z.writestr('DEPTH18_DELTA_MANIFEST.json',json.dumps(manifest,indent=2))
        z.writestr('RESULT_FILE_MANIFEST.json',result_bytes)
    with zipfile.ZipFile(temporary) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(changes)+2
        for f in changes:assert hashlib.sha256(z.read('payload/'+f['path'])).hexdigest()==f['sha256']
    temporary.replace(path)
    receipt={'delta':{'path':str(path),'size':path.stat().st_size,'sha256':digest(path),'entries':len(changes)+2},
             'changed_payload_files':len(changes),'result_files':len(result['files']),
             'baseline_work_sha256':BASE_SHA,'release_gate':'HOLD','engineering_complete':False}
    (out/'GO_DEPTH18_DELIVERY.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (out/'GO_DEPTH18_SHA256SUMS.txt').write_text(f"{digest(path)}  {path.name}\n")
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
