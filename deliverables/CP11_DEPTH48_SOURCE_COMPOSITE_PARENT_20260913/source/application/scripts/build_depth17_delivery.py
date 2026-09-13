#!/usr/bin/env python3
"""Seal cumulative WORK and compact delta, verified against the recovered DEPTH16."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from build_review_delivery import allowed, digest, zip_files

ROOT=Path(__file__).resolve().parents[1]
BASE_SHA='e776e941d7cc1cc64b98bf4e02b538d5f1cf44a53e418c04962b65bcfc646025'
PARENT_SHA='8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb'
STEM='GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-work',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'deliverables')
    args=parser.parse_args();out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    if digest(args.baseline_work)!=BASE_SHA:parser.error('DEPTH16 WORK fingerprint mismatch')
    status=json.loads((ROOT/'verification/current_build/depth17/CURRENT_BUILD_STATUS.json').read_text())
    assert status['python']['one_clean_full_run'] and not status['python']['failures'] and not status['python']['errors']
    frozen=json.loads((ROOT/'verification/current_build/depth17/full_run_source_fingerprint.json').read_text())['files']
    assert all(digest(ROOT/n)==value for n,value in frozen.items()),'FROZEN_SOURCE_CHANGED'
    with zipfile.ZipFile(args.baseline_work) as base:
        old=json.loads(base.read('DELIVERY_FILE_MANIFEST.json'))
        before={f['path']:f for f in old['files']}
        names=set(before)
        for folder in ('src','frontend','tests','tests_frontend','scripts','acceptance','alembic'):
            names.update(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*') if allowed(p))
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'verification/current_build/depth17').rglob('*')
                     if allowed(p) and p.suffix!='.log' and not p.name.startswith(('imported_first','imported_second','interrupted_demo_audit')))
        names.update({'GO_DEPTH17_START_HERE.md','CURRENT_DEPTH_CANDIDATE.json'})
        names.discard('DELIVERY_FILE_MANIFEST.json')
        files=[ROOT/n for n in sorted(names)]
        assert all(allowed(p) for p in files)
        work=zip_files(out/(STEM+'_WORK_20260908.zip'),files)
        with zipfile.ZipFile(work['path']) as z:result=json.loads(z.read('DELIVERY_FILE_MANIFEST.json'))
        changed=[]
        for f in result['files']:
            previous=before.get(f['path'])
            if previous and previous['sha256']==f['sha256']:continue
            changed.append({**f,'before_sha256':previous['sha256'] if previous else None,
                            'mode':(ROOT/f['path']).stat().st_mode&0o777})
        manifest={'build':status['build'],'parent_sha256':PARENT_SHA,'baseline_work_sha256':BASE_SHA,
            'result_work_sha256':work['sha256'],'FINAL_RELEASE_GATE':'HOLD','removed':[], 'files':changed}
        path=out/(STEM+'_DELTA_20260908.zip')
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for f in changed:z.write(ROOT/f['path'],'payload/'+f['path'])
            z.writestr('DEPTH17_DELTA_MANIFEST.json',json.dumps(manifest,indent=2))
            z.writestr('RESULT_FILE_MANIFEST.json',json.dumps(result,ensure_ascii=False,indent=2))
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for f in changed:assert hashlib.sha256(z.read('payload/'+f['path'])).hexdigest()==f['sha256']
        delta={'path':str(path),'size':path.stat().st_size,'sha256':digest(path),'entries':len(changed)+2}
        receipt={'work':work,'delta':delta,'changed_payload_files':len(changed),'baseline_work_sha256':BASE_SHA,'release_gate':'HOLD'}
        (out/'GO_DEPTH17_DELIVERY.json').write_text(json.dumps(receipt,indent=2)+'\n')
        (out/'GO_DEPTH17_SHA256SUMS.txt').write_text(''.join(f"{f['sha256']}  {Path(f['path']).name}\n" for f in (work,delta)))
        print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
