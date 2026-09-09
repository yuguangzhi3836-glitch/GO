"""Materialize DEPTH30 from the exact restored DEPTH29 archive in a NEW directory.

Reads only fingerprinted parent files; does not copy caches, credentials or history.
Does not run application code or install dependencies.
"""
import argparse, hashlib, json, os, tempfile, zipfile
from pathlib import Path, PurePosixPath

EXPECTED_DELTA_SHA256 = '6803c349f241feae33a879d91243bc6bb1ff23c77701f98d69a0ec06d9b5d107'
EXPECTED_SOURCE_TREE = 'f576c976bfe8f34d3182ba232fe1290c374346106c602a4fffe4935366f7a961'

def sha(data): return hashlib.sha256(data).hexdigest()
def tree(fp): return sha(''.join(f'{k}\0{v}\n' for k,v in sorted(fp.items())).encode())
def relative(value):
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not p.parts or '\\' in value or str(p)!=value:
        raise ValueError('UNSAFE_SOURCE_PATH')
    return p

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--delta',type=Path,default=Path(__file__).with_name('GO_CP11_DEPTH30_DELTA_20260909.zip'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    parent=args.parent.resolve(strict=True);output=args.output.absolute()
    if output.exists() or output.is_symlink() or output==parent or parent in output.parents:
        raise ValueError('NEW_SEPARATE_OUTPUT_REQUIRED')
    if sha(args.delta.read_bytes())!=EXPECTED_DELTA_SHA256:raise ValueError('DELTA_INTEGRITY_MISMATCH')
    with zipfile.ZipFile(args.delta) as z:
        manifest=json.loads(z.read('SOURCE_MANIFEST.json'))
        before=json.loads(z.read('PARENT_SOURCE_FINGERPRINT.json'))
        final=json.loads(z.read('SOURCE_FINGERPRINT.json'))
        names=z.namelist()
        expected={'SOURCE_MANIFEST.json','PARENT_SOURCE_FINGERPRINT.json','SOURCE_FINGERPRINT.json'}|{'source_changes/'+x['path'] for x in manifest['files']}
        if len(names)!=len(set(names)) or set(names)!=expected:raise ValueError('ARCHIVE_MEMBERS_MISMATCH')
        if tree(final)!=EXPECTED_SOURCE_TREE or tree(before)!=manifest['parent_materialized_source_tree_sha256']:raise ValueError('FINGERPRINT_MISMATCH')
        if set(before)-set(final):raise ValueError('UNEXPECTED_SOURCE_REMOVAL')
        payload={}
        for rel,expected_hash in before.items():
            p=parent/relative(rel)
            if not p.is_file() or p.is_symlink() or p.resolve()!=p or sha(p.read_bytes())!=expected_hash:
                raise ValueError('PARENT_SOURCE_MISMATCH:'+rel)
        for row in manifest['files']:
            relative(row['path'])
            if before.get(row['path'])!=row['before_sha256']:raise ValueError('BEFORE_HASH_MISMATCH')
            data=z.read('source_changes/'+row['path'])
            if len(data)!=row['size'] or sha(data)!=row['sha256'] or final[row['path']]!=row['sha256']:raise ValueError('CHANGED_SOURCE_MISMATCH')
            payload[row['path']]=data
        if set(payload)!={p for p in final if before.get(p)!=final[p]}:raise ValueError('DELTA_COVERAGE_MISMATCH')
        output.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='go-depth30-restore-',dir=output.parent) as temp:
            candidate=Path(temp)/'source';candidate.mkdir()
            for rel,expected_hash in final.items():
                data=payload[rel] if rel in payload else (parent/relative(rel)).read_bytes()
                if sha(data)!=expected_hash:raise ValueError('RESTORED_SOURCE_MISMATCH:'+rel)
                dest=candidate/relative(rel);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            if output.exists() or output.is_symlink():raise ValueError('OUTPUT_APPEARED')
            os.rename(candidate,output)
    print(json.dumps(dict(parent_files_verified=len(before),restored_files_verified=len(final),source_tree_sha256=tree(final),delta_sha256=EXPECTED_DELTA_SHA256,scope='offline source materialization only',independent_ci=False,FINAL_RELEASE_GATE='HOLD'),indent=2))
if __name__=='__main__':main()
