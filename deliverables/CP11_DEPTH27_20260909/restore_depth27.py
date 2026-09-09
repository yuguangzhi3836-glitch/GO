"""Restore into a new directory after checking the exact DEPTH26 source bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not p.parts or '\\' in value:
        raise ValueError('UNSAFE_ARCHIVE_PATH')
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', required=True, type=Path)
    parser.add_argument('--delta', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    parent = args.parent.resolve(strict=True)
    output = args.output.absolute()
    if output.exists() or parent == output or parent in output.parents:
        raise SystemExit('NEW_SEPARATE_OUTPUT_DIRECTORY_REQUIRED')
    with zipfile.ZipFile(args.delta) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('DUPLICATE_ARCHIVE_MEMBER')
        manifest = json.loads(z.read('SOURCE_MANIFEST.json'))
        previous = json.loads(z.read('PARENT_SOURCE_FINGERPRINT.json'))
        final = json.loads(z.read('SOURCE_FINGERPRINT.json'))
        for rel, expected in previous.items():
            p = parent / relative(rel)
            if not p.is_file() or digest(p) != expected:
                raise ValueError('PARENT_SOURCE_MISMATCH:' + rel)
        for row in manifest['files']:
            rel = relative(row['path'])
            p = parent / rel
            actual = digest(p) if p.is_file() else None
            if actual != row['before_sha256']:
                raise ValueError('PARENT_CHANGED_FILE_MISMATCH:' + str(rel))
            data = z.read('source_changes/' + str(rel))
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('DELTA_BYTES_MISMATCH:' + str(rel))
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='go-depth27-restore-', dir=output.parent) as temp:
            candidate = Path(temp) / 'candidate'
            shutil.copytree(parent, candidate, ignore=shutil.ignore_patterns(
                '.git', '.preview', 'node_modules', 'gate_runtime', '__pycache__', '.pytest_cache', 'deliverables'))
            for row in manifest['files']:
                p = candidate / relative(row['path'])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(z.read('source_changes/' + row['path']))
            for rel, expected in final.items():
                if digest(candidate / relative(rel)) != expected:
                    raise ValueError('RESTORED_SOURCE_MISMATCH:' + rel)
            if output.exists():
                raise ValueError('OUTPUT_APPEARED_DURING_RESTORE')
            os.rename(candidate, output)
    print(json.dumps({'restored_files_verified': len(final), 'parent_files_verified': len(previous),
                      'source_tree_sha256': manifest['source_tree_sha256'],
                      'delta_sha256': digest(args.delta), 'output': str(output),
                      'FINAL_RELEASE_GATE': 'HOLD'}, indent=2))


if __name__ == '__main__':
    main()
