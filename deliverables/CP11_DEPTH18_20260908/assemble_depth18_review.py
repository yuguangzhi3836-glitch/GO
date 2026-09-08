#!/usr/bin/env python3
"""Restore DEPTH18 from pinned parent + DEPTH17 WORK + reviewed DEPTH18 delta."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

PARENT_SHA = '8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb'
BASE_SHA = '1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def safe(name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('UNSAFE_ARCHIVE_PATH:'+name)
    return p


def preflight(z):
    seen=set()
    for info in z.infolist():
        safe(info.filename)
        if info.filename in seen or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('DUPLICATE_OR_LINK_ARCHIVE_ENTRY:'+info.filename)
        seen.add(info.filename)


def verify_entries(z, entries, prefix=''):
    for f in entries:
        safe(f['path'])
        data=z.read(prefix+f['path'])
        if len(data)!=f['size'] or hashlib.sha256(data).hexdigest()!=f['sha256']:
            raise ValueError('PAYLOAD_INTEGRITY_FAILURE:'+f['path'])


def extract(z, output, prefix=''):
    for info in z.infolist():
        if not info.filename.startswith(prefix):continue
        p=safe(info.filename[len(prefix):])
        if '__pycache__' in p.parts or p.suffix in {'.pyc','.pyo'}:continue
        target=output/str(p)
        if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
        target.parent.mkdir(parents=True,exist_ok=True)
        with z.open(info) as source,target.open('wb') as sink:shutil.copyfileobj(source,sink)
        if os.name!='nt':target.chmod(0o755 if (info.external_attr>>16)&0o111 else 0o644)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('parent','base-work','delta','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(); output=args.output.resolve()
    if output.exists():parser.error('Output must be a new directory')
    if sha(args.parent)!=PARENT_SHA or sha(args.base_work)!=BASE_SHA:
        parser.error('Locked parent or DEPTH17 WORK SHA256 mismatch')
    with zipfile.ZipFile(args.parent) as parent,zipfile.ZipFile(args.base_work) as base,zipfile.ZipFile(args.delta) as delta:
        for z in (parent,base,delta):preflight(z)
        old=json.loads(base.read('DELIVERY_FILE_MANIFEST.json'))
        change=json.loads(delta.read('DEPTH18_DELTA_MANIFEST.json'))
        result=json.loads(delta.read('RESULT_FILE_MANIFEST.json'))
        if change['baseline_work_sha256']!=BASE_SHA or change['parent_sha256']!=PARENT_SHA or change['removed']:
            parser.error('Unsupported delta lineage or removals')
        verify_entries(base,old['files']);verify_entries(delta,change['files'],'payload/')
        known={f['path']:f for f in old['files']}
        for f in change['files']:
            before=known.get(f['path'])
            if (before['sha256'] if before else None)!=f['before_sha256']:
                parser.error('Delta baseline mismatch: '+f['path'])
            known[f['path']]={k:f[k] for k in ('path','size','sha256')}
        expected={f['path']:{k:f[k] for k in ('path','size','sha256')} for f in result['files']}
        normalized={n:{k:f[k] for k in ('path','size','sha256')} for n,f in known.items()}
        if expected!=normalized or len(expected)!=len(result['files']):
            parser.error('Result manifest does not match composed delta')
        if set(delta.namelist())!={'DEPTH18_DELTA_MANIFEST.json','RESULT_FILE_MANIFEST.json',*('payload/'+f['path'] for f in change['files'])}:
            parser.error('Unexpected delta entries')
        output.mkdir(parents=True)
        try:
            extract(parent,output);extract(base,output);extract(delta,output,'payload/')
            (output/'DELIVERY_FILE_MANIFEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            for f in result['files']:
                if sha(output/f['path'])!=f['sha256']:raise ValueError('RESTORED_HASH_MISMATCH:'+f['path'])
            if os.name!='nt':
                for name in ('python','python3','python3.13'):(output/'gate_runtime/python/bin'/name).chmod(0o755)
            receipt={'parent_sha256':PARENT_SHA,'base_work_sha256':BASE_SHA,'delta_sha256':sha(args.delta),
                'verified_files':len(result['files']),'migration_head':'0125_regional_queue','release_gate':'HOLD'}
            (output/'DEPTH18_RESTORATION.json').write_text(json.dumps(receipt,indent=2)+'\n')
        except BaseException:
            shutil.rmtree(output)
            raise
    print(json.dumps(receipt,indent=2))
    print('Read GO_DEPTH18_START_HERE.md; this is an engineering review copy.')


if __name__=='__main__':main()
