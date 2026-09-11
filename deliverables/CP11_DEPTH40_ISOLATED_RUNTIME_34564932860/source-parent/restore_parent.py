from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or str(p) != name:
        raise ValueError('UNSAFE_PATH:' + name)
    return p


def tree_hash(fp: dict[str, str]) -> str:
    material = ''.join(f'{k}\0{v}\n' for k, v in sorted(fp.items())).encode()
    return sha256_bytes(material)


def verify_tree(root: Path, fp: dict[str, str]) -> None:
    actual_files = {
        str(p.relative_to(root)).replace('\\', '/')
        for p in root.rglob('*') if p.is_file() and not p.is_symlink()
    }
    if actual_files != set(fp):
        missing = sorted(set(fp) - actual_files)[:20]
        extra = sorted(actual_files - set(fp))[:20]
        raise ValueError(f'FILESET_MISMATCH:missing={missing}:extra={extra}')
    for name, expected in fp.items():
        p = root / safe_path(name)
        if p.is_symlink():
            raise ValueError('SYMLINK_FORBIDDEN:' + name)
        actual = sha256_bytes(p.read_bytes())
        if actual != expected:
            raise ValueError('SOURCE_MISMATCH:' + name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    package = args.package.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('NEW_OUTPUT_REQUIRED')
    manifest = json.loads((package / 'MANIFEST.json').read_text())
    fp = json.loads((package / 'SOURCE_FINGERPRINT.json').read_text())
    archive = package / manifest['archive_file']
    if sha256_bytes(archive.read_bytes()) != manifest['archive_sha256']:
        raise ValueError('ARCHIVE_SHA256_MISMATCH')
    if tree_hash(fp) != manifest['source_tree_sha256']:
        raise ValueError('SOURCE_TREE_SHA256_MISMATCH')
    output.mkdir(parents=True)
    with tarfile.open(archive, 'r:gz') as tf:
        for member in tf.getmembers():
            safe_path(member.name)
            if member.issym() or member.islnk():
                raise ValueError('LINK_FORBIDDEN:' + member.name)
        tf.extractall(output, filter='data')
    verify_tree(output, fp)
    print(json.dumps({
        'status': 'PASS',
        'verified_files': len(fp),
        'source_tree_sha256': tree_hash(fp),
        'archive_sha256': manifest['archive_sha256'],
        'candidate': manifest['candidate'],
        'deployment': 'NOT_AUTHORIZED',
    }, sort_keys=True))


if __name__ == '__main__':
    main()
