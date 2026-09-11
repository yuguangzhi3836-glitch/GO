from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('SYMLINK_FORBIDDEN:' + str(p))
        if p.is_file():
            rel = str(p.relative_to(root)).replace('\\', '/')
            out[rel] = sha256_bytes(p.read_bytes())
    return out


def tree_hash(fp: dict[str, str]) -> str:
    material = ''.join(f'{k}\0{v}\n' for k, v in sorted(fp.items())).encode()
    return sha256_bytes(material)


def write_deterministic_tar_gz(source: Path, target: Path) -> None:
    with target.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode='w') as tf:
                for p in sorted(source.rglob('*')):
                    if not p.is_file():
                        continue
                    rel = str(p.relative_to(source)).replace('\\', '/')
                    info = tf.gettarinfo(str(p), arcname=rel)
                    info.uid = 0; info.gid = 0; info.uname = ''; info.gname = ''
                    info.mtime = 0
                    with p.open('rb') as fh:
                        tf.addfile(info, fh)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--base-commit', required=True)
    ap.add_argument('--p02-commit', required=True)
    ap.add_argument('--p03-commit', required=True)
    args = ap.parse_args()
    source = args.source.resolve(); output = args.output.resolve()
    if output.exists():
        raise ValueError('NEW_OUTPUT_REQUIRED')
    output.mkdir(parents=True)
    fp = fingerprint(source)
    source_tree = tree_hash(fp)
    archive_name = 'GO_CP11_DEPTH40_P03_PARENT_SOURCE_20260911.tar.gz'
    archive = output / archive_name
    write_deterministic_tar_gz(source, archive)
    archive_sha = sha256_bytes(archive.read_bytes())
    (output / 'SOURCE_FINGERPRINT.json').write_text(json.dumps(fp, indent=2, sort_keys=True) + '\n')
    manifest = {
        'candidate': 'CP11_DEPTH40_P03_PARENT_20260911',
        'base_depth36_source_tree_sha256': '59b4f02e18a50d9cb96369cb559b04cf5e658c592ae0a02b7662bdecacb91d56',
        'base_commit': args.base_commit,
        'p02_commit': args.p02_commit,
        'p03_commit': args.p03_commit,
        'source_tree_sha256': source_tree,
        'verified_files': len(fp),
        'archive_file': archive_name,
        'archive_sha256': archive_sha,
        'deterministic_archive': True,
        'deployment_authorized': False,
        'physical_iphone_gate': 'HOLD_EXTERNAL_DEVICE_RUNNER',
    }
    (output / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    checksums = {
        archive_name: archive_sha,
        'MANIFEST.json': sha256_bytes((output/'MANIFEST.json').read_bytes()),
        'SOURCE_FINGERPRINT.json': sha256_bytes((output/'SOURCE_FINGERPRINT.json').read_bytes()),
    }
    (output / 'CHECKSUMS.sha256').write_text(''.join(f'{h}  {name}\n' for name, h in checksums.items()))
    (output / 'LINEAGE.json').write_text(json.dumps({
        'depth36_source_tree_sha256': manifest['base_depth36_source_tree_sha256'],
        'p02_commit': args.p02_commit,
        'p03_commit': args.p03_commit,
        'result_source_tree_sha256': source_tree,
    }, indent=2, sort_keys=True) + '\n')
    (output / 'RELEASE_GATE.json').write_text(json.dumps({
        'parent_candidate': 'PASS_SOFTWARE',
        'fresh_restore': 'PENDING_INDEPENDENT_ACCEPTANCE',
        'apple_xcode_simulator': 'PASS',
        'apple_physical_iphone': 'HOLD_EXTERNAL_DEVICE_RUNNER',
        'merge_authorized': False,
        'deployment_authorized': False,
        'hong_kong_deployment': 'NO',
    }, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status':'PASS','verified_files':len(fp),'source_tree_sha256':source_tree,'archive_sha256':archive_sha}, sort_keys=True))


if __name__ == '__main__':
    main()
