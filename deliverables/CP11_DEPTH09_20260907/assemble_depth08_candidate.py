#!/usr/bin/env python3
"""Restore DEPTH08 into a new directory from exact CP11 + DEPTH07 + sealed delta."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

PARENT_SHA = '8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb'
WORK_SHA = '25e92a436ecd811794cbe90b1e000f9cfe71eeca8b420eaeff151e62ae61b808'
ROOTS = {'src', 'frontend', 'tests', 'tests_frontend', 'scripts', 'alembic'}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_name(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('UNSAFE_ARCHIVE_PATH')
    return p


def preflight(z):
    names = z.namelist()
    if len(names) != len(set(names)):
        raise ValueError('DUPLICATE_ARCHIVE_MEMBER')
    for info in z.infolist():
        safe_name(info.filename)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('ARCHIVE_SYMLINK_REJECTED')
    bad = z.testzip()
    if bad:
        raise ValueError('ARCHIVE_CRC_FAILED:' + bad)


def extract(z, output):
    for info in z.infolist():
        path = safe_name(info.filename)
        if '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
            continue
        target = output / str(path)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as source, target.open('wb') as dest:
            shutil.copyfileobj(source, dest)
        if os.name != 'nt':
            target.chmod(0o755 if (info.external_attr >> 16) & 0o111 else 0o644)


def source_entries(root):
    entries = []
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if rel.parts[0] not in ROOTS and rel.as_posix() not in {'pyproject.toml', 'alembic.ini'}:
            continue
        if '__pycache__' in rel.parts or path.suffix in {'.pyc', '.pyo'} or not path.is_file():
            continue
        entries.append({'path': rel.as_posix(), 'sha256': sha(path)})
    return entries


def tree_hash(entries):
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def restore(parent, work, delta, output):
    if output.exists():
        raise ValueError('OUTPUT_MUST_BE_NEW_DIRECTORY')
    if sha(parent) != PARENT_SHA or sha(work) != WORK_SHA:
        raise ValueError('EXACT_DEPENDENCY_HASH_MISMATCH')
    with zipfile.ZipFile(parent) as pz, zipfile.ZipFile(work) as wz, zipfile.ZipFile(delta) as dz:
        for z in (pz, wz, dz):
            preflight(z)
        manifest = json.loads(dz.read('DEPTH08_DELTA_MANIFEST.json'))
        if manifest['parent_sha256'] != PARENT_SHA or manifest['depth07_work_sha256'] != WORK_SHA:
            raise ValueError('DELTA_LINEAGE_MISMATCH')
        expected = {'DEPTH08_DELTA_MANIFEST.json'} | {'payload/' + f['path'] for f in manifest['files']}
        if set(dz.namelist()) != expected:
            raise ValueError('UNMANIFESTED_DELTA_MEMBER')
        for f in manifest['files']:
            safe_name(f['path'])
            data = dz.read('payload/' + f['path'])
            if hashlib.sha256(data).hexdigest() != f['sha256'] or len(data) != f['size']:
                raise ValueError('DELTA_PAYLOAD_HASH_MISMATCH')
        output.mkdir(parents=True)
        try:
            extract(pz, output)
            extract(wz, output)
            for f in manifest['files']:
                target = output / f['path']
                actual = sha(target) if target.is_file() else None
                if actual != f['before_sha256']:
                    raise ValueError('BASE_FILE_MISMATCH:' + f['path'])
            for f in manifest['files']:
                target = output / f['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(dz.read('payload/' + f['path']))
                if os.name != 'nt':
                    target.chmod(f['mode'])
            source_sha = tree_hash(source_entries(output))
            if source_sha != manifest['source_tree_sha256']:
                raise ValueError('RESTORED_SOURCE_TREE_MISMATCH')
            if os.name != 'nt':
                for name in ('python', 'python3', 'python3.13'):
                    (output / 'gate_runtime/python/bin' / name).chmod(0o755)
            receipt = {'build': manifest['build'], 'parent_sha256': PARENT_SHA,
                'depth07_work_sha256': WORK_SHA, 'delta_sha256': sha(delta),
                'source_tree_sha256': source_sha, 'payload_files_verified': len(manifest['files']),
                'FINAL_RELEASE_GATE': 'HOLD', 'deployed': False}
            (output / 'DEPTH08_RESTORATION.json').write_text(json.dumps(receipt, indent=2) + '\n')
        except BaseException:
            shutil.rmtree(output)
            raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'depth07-work', 'delta', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(restore(args.parent, args.depth07_work, args.delta, args.output.resolve()), indent=2))


if __name__ == '__main__':
    main()
