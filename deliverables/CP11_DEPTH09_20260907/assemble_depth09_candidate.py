#!/usr/bin/env python3
"""Restore exact DEPTH08, then apply the reviewed DEPTH09 delta to a new directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

from assemble_depth08_candidate import restore as restore08, preflight, safe_name, sha, source_entries, tree_hash

DEPTH08_SHA = 'e6446a852d1806cc4afe0ae0ec88a79e228484518dcf21039fea551342507c0a'
DEPTH08_SOURCE = 'c4c00f4476a3c7041ae7ed10a10bef60dc2efcf8c56e86c83d35ca24748310ea'


def restore(parent, work, depth08, delta, output):
    if output.exists():raise ValueError('OUTPUT_MUST_BE_NEW_DIRECTORY')
    if sha(depth08)!=DEPTH08_SHA:raise ValueError('DEPTH08_ARCHIVE_MISMATCH')
    with zipfile.ZipFile(delta) as z:
        preflight(z)
        m=json.loads(z.read('DEPTH09_DELTA_MANIFEST.json'))
        if m['depth08_delta_sha256']!=DEPTH08_SHA or m['baseline_source_tree_sha256']!=DEPTH08_SOURCE:
            raise ValueError('DEPTH09_LINEAGE_MISMATCH')
        if set(z.namelist())!={'DEPTH09_DELTA_MANIFEST.json'}|{'payload/'+x['path'] for x in m['files']}:
            raise ValueError('UNMANIFESTED_DELTA_FILE')
        for f in m['files']:
            safe_name(f['path']);data=z.read('payload/'+f['path'])
            if hashlib.sha256(data).hexdigest()!=f['sha256'] or len(data)!=f['size']:
                raise ValueError('DEPTH09_PAYLOAD_HASH_MISMATCH')
        restore08(parent,work,depth08,output)
        try:
            if tree_hash(source_entries(output))!=DEPTH08_SOURCE:raise ValueError('DEPTH08_SOURCE_MISMATCH')
            for f in m['files']:
                p=output/f['path']
                if (sha(p) if p.is_file() else None)!=f['before_sha256']:
                    raise ValueError('DEPTH09_BEFORE_HASH_MISMATCH:'+f['path'])
            for f in m['files']:
                p=output/f['path'];p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(z.read('payload/'+f['path']))
                if os.name!='nt':p.chmod(f['mode'])
            source_sha=tree_hash(source_entries(output))
            if source_sha!=m['source_tree_sha256']:raise ValueError('DEPTH09_RESTORED_SOURCE_MISMATCH')
            receipt={'build':m['build'],'delta_sha256':sha(delta),'depth08_delta_sha256':DEPTH08_SHA,
                     'source_tree_sha256':source_sha,'payload_files_verified':len(m['files']),
                     'FINAL_RELEASE_GATE':'HOLD','HOTEL_REPLICATION_GATE':'HOLD','deployed':False}
            (output/'DEPTH09_RESTORATION.json').write_text(json.dumps(receipt,indent=2)+'\n')
            return receipt
        except BaseException:
            shutil.rmtree(output)
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('parent','depth07-work','depth08-delta','delta','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(restore(args.parent,args.depth07_work,args.depth08_delta,args.delta,args.output.resolve()),indent=2))
