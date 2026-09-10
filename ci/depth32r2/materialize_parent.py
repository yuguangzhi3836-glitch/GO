"""Offline preparation only: restore the sealed DEPTH26 -> 27 -> 28 source chain."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--depth26', type=Path, required=True)
    parser.add_argument('--depth27', type=Path, required=True)
    parser.add_argument('--depth28', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('NEW_OUTPUT_REQUIRED')
    parts = json.loads((args.depth26 / 'SOURCE_PARTS.json').read_text())
    payloads = []
    for row in parts['parts']:
        if Path(row['path']).name != row['path']:
            raise ValueError('UNSAFE_PART_PATH')
        data = (args.depth26 / row['path']).read_bytes()
        if len(data) != row['size'] or sha(data) != row['sha256']:
            raise ValueError('PART_INTEGRITY_MISMATCH')
        payloads.append(data)
    archive = b''.join(payloads)
    if sha(archive) != '7def8724d0bd5231fdd9b7ec8548951ed01a896d6b5d059d6d326d6bb252676a':
        raise ValueError('FROZEN_DEPTH26_ARCHIVE_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='go-offline-lineage-') as temporary:
        base = Path(temporary) / 'depth26'
        parent = Path(temporary) / 'depth27'
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            if len(zipped.namelist()) != len(set(zipped.namelist())):
                raise ValueError('DUPLICATE_MEMBER')
            for info in zipped.infolist():
                rel = PurePosixPath(info.filename)
                if rel.is_absolute() or '..' in rel.parts or '\\' in info.filename:
                    raise ValueError('UNSAFE_ARCHIVE_PATH')
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('ARCHIVE_SYMLINK')
                target = base / rel
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zipped.read(info))
        for number, package, source, target in (
            (27, args.depth27, base, parent),
            (28, args.depth28, parent, args.output),
        ):
            delta = ('GO_CP11_DEPTH27_DELTA_20260909.zip' if number == 27
                     else 'GO_CP11_DEPTH28_V14_DELTA_20260909.zip')
            subprocess.run([sys.executable, str(package / f'restore_depth{number}.py'),
                            '--parent', str(source), '--delta', str(package / delta),
                            '--output', str(target)], check=True)
    fingerprint = json.loads((args.depth28 / 'SOURCE_FINGERPRINT.json').read_text())
    for rel, expected in fingerprint.items():
        if sha((args.output / rel).read_bytes()) != expected:
            raise ValueError('FINAL_SOURCE_MISMATCH:' + rel)
    print(json.dumps({'verified_files': len(fingerprint), 'result': 'PASS',
                      'scope': 'offline archive materialization only',
                      'independent_ci': False, 'release_gate': 'HOLD'}))


if __name__ == '__main__':
    main()
