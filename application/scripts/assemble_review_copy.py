#!/usr/bin/env python3
"""Restore this review build from the verified CP11 parent and the compact WORK ZIP."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import stat
import zipfile

PARENT_SHA='8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def extract(archive,destination):
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name=PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ':' in info.filename:
                raise ValueError('UNSAFE_ARCHIVE_PATH')
            if '__pycache__' in name.parts or name.suffix in {'.pyc','.pyo'}:continue
            mode=info.external_attr>>16
            if stat.S_ISLNK(mode):raise ValueError('SYMLINK_NOT_SUPPORTED')
            target=destination/str(name)
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
            if os.name!='nt':target.chmod(0o755 if mode&0o111 else 0o644)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',required=True,type=Path)
    parser.add_argument('--work',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path,help='New directory; existing paths are never overwritten')
    args=parser.parse_args();output=args.output.resolve()
    if output.exists():parser.error('Output directory already exists')
    if digest(args.parent)!=PARENT_SHA:parser.error('The supplied parent does not match the locked CP11 SHA256')
    with zipfile.ZipFile(args.work) as z:
        manifest=json.loads(z.read('DELIVERY_FILE_MANIFEST.json'))
        delta=json.loads(z.read('acceptance/RUNTIME_DELTA.json'))
        if delta['parent_sha256']!=PARENT_SHA:parser.error('Work package is for another parent')
        if delta['removed']:parser.error('This assembler does not apply runtime removals')
        for entry in manifest['files']:
            data=z.read(entry['path'])
            if len(data)!=entry['size'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
                parser.error('Work archive integrity failed: '+entry['path'])
    # Hash checking and path preflight happen before this newly owned output is used.
    output.mkdir(parents=True)
    try:
        extract(args.parent,output);extract(args.work,output)
        for entry in manifest['files']:
            if digest(output/entry['path'])!=entry['sha256']:raise ValueError('RESTORED_FILE_HASH_MISMATCH')
        if os.name!='nt':
            for name in ['python','python3','python3.13']:(output/'gate_runtime/python/bin'/name).chmod(0o755)
        (output/'PARENT_RESTORATION.json').write_text(json.dumps({'parent_sha256':PARENT_SHA,
            'work_sha256':digest(args.work),'verified_patch_files':len(manifest['files']),
            'runtime_delta_files':len(delta['changed']),'release_gate':'HOLD'},indent=2))
    except Exception:
        shutil.rmtree(output)
        raise
    print('Restored verified review copy:',output)
    guide=next((name for name in ['GO_DEPTH16_START_HERE.md','GO_DEPTH15_START_HERE.md','GO_DEPTH14_START_HERE.md','GO_DEPTH13_START_HERE.md','GO_DEPTH12_START_HERE.md','GO_DEPTH11_START_HERE.md','GO_DEPTH10_START_HERE.md','GO_DEPTH09_START_HERE.md','GO_DEPTH08_START_HERE.md','GO_DEPTH07_START_HERE.md','GO_DEPTH06_START_HERE.md','GO_DEPTH05_START_HERE.md','GO_DEPTH04_START_HERE.md'] if (output/name).exists()),'GO_MASTER03_START_HERE.md')
    print('Read '+guide+'. This is an engineering review copy, not a live release.')

if __name__=='__main__':main()
