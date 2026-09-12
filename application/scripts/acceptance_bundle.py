"""Build/verify an exact, deterministic source bundle without downloading anything."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile
from acceptance_runtime import verify_source, tree_hash

sha = lambda data: hashlib.sha256(data).hexdigest()


def safe_member(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and str(p) == name


def build(root, fp, expected, destination):
    verify_source(root, fp, expected)
    payload = {'source/' + rel: (root / rel).read_bytes() for rel in sorted(fp)}
    payload['SOURCE_FINGERPRINT.json'] = (json.dumps(fp, indent=2, ensure_ascii=False) + '\n').encode()
    metadata = {'schema': 'go.acceptance-source-bundle.v1', 'source_tree_sha256': expected,
        'source_files': len(fp), 'files': {k: sha(v) for k, v in sorted(payload.items())},
        'scope': 'SOURCE_BUNDLE_ONLY', 'runtime_dependencies_included': False,
        'browser_gate': 'HOLD', 'final_release': 'HOLD'}
    payload['BUNDLE_MANIFEST.json'] = (json.dumps(metadata, indent=2) + '\n').encode()
    # Exclusive creation preserves prior artifacts instead of replacing them.
    with Path(destination).open('xb') as output:
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 9, 10, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                zipped.writestr(info, data)
    return verify(Path(destination), sha(Path(destination).read_bytes()), expected)


def verify(archive, expected_archive_sha, expected_tree, output=None):
    if sha(archive.read_bytes()) != expected_archive_sha:
        raise ValueError('ARCHIVE_CHECKSUM_MISMATCH')
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if len(names) != len(set(names)) or any(not safe_member(n) for n in names):
            raise ValueError('UNSAFE_ARCHIVE_MEMBERS')
        if any(not stat.S_ISREG(i.external_attr >> 16) for i in zipped.infolist()):
            raise ValueError('NONREGULAR_ARCHIVE_MEMBER')
        meta = json.loads(zipped.read('BUNDLE_MANIFEST.json'))
        fp = json.loads(zipped.read('SOURCE_FINGERPRINT.json'))
        if (meta.get('schema') != 'go.acceptance-source-bundle.v1'
                or meta.get('source_tree_sha256') != expected_tree
                or tree_hash(fp) != expected_tree or meta.get('source_files') != len(fp)):
            raise ValueError('BUNDLE_SOURCE_BINDING_MISMATCH')
        expected_names = {'source/' + rel for rel in fp} | {'SOURCE_FINGERPRINT.json'}
        if set(meta['files']) != expected_names or set(names) != expected_names | {'BUNDLE_MANIFEST.json'}:
            raise ValueError('BUNDLE_FILE_SET_MISMATCH')
        for name, digest in meta['files'].items():
            data = zipped.read(name)
            if sha(data) != digest:
                raise ValueError('BUNDLE_FILE_CHECKSUM_MISMATCH')
            if name.startswith('source/') and sha(data) != fp[name[len('source/'):]]:
                raise ValueError('BUNDLE_SOURCE_FILE_MISMATCH')
        if output is not None:
            output.mkdir(parents=False, exist_ok=False)
            for name in names:
                path = output / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(zipped.read(name))
            verify_source(output / 'source', fp, expected_tree)
    return {'archive_sha256': expected_archive_sha, 'source_tree_sha256': expected_tree,
            'verified_files': len(fp), 'scope': 'OFFLINE_BUNDLE_INTEGRITY', 'final_release': 'HOLD'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--fingerprint', type=Path, required=True)
    p.add_argument('--expected-tree', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(build(args.source, json.loads(args.fingerprint.read_text()), args.expected_tree, args.output)))


if __name__ == '__main__':
    main()
