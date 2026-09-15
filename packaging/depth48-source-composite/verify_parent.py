"""Verify the source composite offline. No image load, build, or application run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def require(value, code):
    if not value:
        raise ValueError(code)


def safe_name(name):
    require(isinstance(name, str) and name and
            all(p not in ('', '.', '..') for p in name.split('/')) and
            not any(c in name for c in '\\\r\n\0:'), 'UNSAFE_NAME')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    """Hash raw bytes and executable modes exactly as Git does; reject links."""
    root = Path(root)
    require(stat.S_ISDIR(root.lstat().st_mode), 'ROOT_DIRECTORY')
    rows, trees = {}, {}

    def visit(directory):
        entries = []
        for path in directory.iterdir():
            name = path.relative_to(root).as_posix()
            safe_name(name)
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                digest = visit(path)
                mode, key = '40000', os.fsencode(path.name) + b'/'
            else:
                require(stat.S_ISREG(info.st_mode), 'SPECIAL_FILE:' + name)
                mode = '100755' if info.st_mode & 0o111 else '100644'
                blob = hashlib.sha1(b'blob ' + str(info.st_size).encode() + b'\0')
                sha = hashlib.sha256()
                count = 0
                with path.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        count += len(chunk)
                        blob.update(chunk)
                        sha.update(chunk)
                require(count == info.st_size, 'FILE_CHANGED:' + name)
                digest, key = blob.hexdigest(), os.fsencode(path.name)
                rows[name] = {'mode': mode, 'bytes': count, 'git_blob': digest,
                              'sha256': sha.hexdigest()}
            entries.append((key, mode.encode() + b' ' + os.fsencode(path.name) +
                            b'\0' + bytes.fromhex(digest)))
        data = b''.join(row for _, row in sorted(entries))
        digest = hashlib.sha1(b'tree ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        trees[directory.relative_to(root).as_posix()] = digest
        return digest

    visit(root)
    return rows, trees


def verify(root, expected_manifest_sha256):
    root = Path(root)
    require(not root.is_symlink() and root.is_dir(), 'ROOT_DIRECTORY')
    require({p.name for p in root.iterdir()} == {
        'source', 'previous_parent', 'PARENT_MANIFEST.json', 'MANIFEST.sha256',
        'README.md', 'verify_parent.py', 'create_archive.py'}, 'ROOT_FILE_SET')
    for path in root.iterdir():
        require(not path.is_symlink(), 'ROOT_SYMLINK')
    require(sha256(root / 'PARENT_MANIFEST.json') == expected_manifest_sha256,
            'EXTERNAL_MANIFEST_SHA256')
    manifest = json.loads((root / 'PARENT_MANIFEST.json').read_text())
    require(manifest['schema'] == 'go.source-composite-parent.v1', 'SCHEMA')
    require(manifest['package_kind'] == 'SOURCE_COMPOSITE_CANDIDATE' and
            manifest['new_runtime']['status'] == 'NOT_BUILT' and
            manifest['gates']['FINAL_RELEASE'] == 'HOLD', 'PACKAGE_SCOPE')
    metadata = manifest['metadata_sha256']
    require(set(metadata) == {'README.md', 'verify_parent.py', 'create_archive.py'},
            'METADATA_FILE_SET')
    for name, digest in metadata.items():
        require(sha256(root / name) == digest, 'METADATA_HASH:' + name)
    sums = dict(metadata, **{'PARENT_MANIFEST.json': expected_manifest_sha256})
    expected_sums = ''.join(f'{digest}  {name}\n' for name, digest in sorted(sums.items()))
    require((root / 'MANIFEST.sha256').read_text() == expected_sums, 'MANIFEST_SUMS')
    inventories = {}
    for folder in ('source', 'previous_parent'):
        rows, trees = inventory(root / folder)
        expected = manifest['payloads'][folder]
        require(trees['.'] == expected['git_tree'], 'PAYLOAD_GIT_TREE:' + folder)
        require(len(rows) == expected['files'] and
                sum(row['bytes'] for row in rows.values()) == expected['bytes'],
                'PAYLOAD_COUNTS:' + folder)
        inventories[folder] = rows, trees
    rows, trees = inventories['source']
    app = manifest['application']
    require(trees['application'] == app['git_tree'], 'APPLICATION_GIT_TREE')
    fingerprints = {name[len('application/'):]: row['sha256']
                    for name, row in rows.items() if name.startswith('application/')}
    expected = json.loads((root / 'source' / app['fingerprint_path']).read_text())
    require(fingerprints == expected and len(fingerprints) == app['files'],
            'APPLICATION_FINGERPRINT')
    digest = hashlib.sha256(''.join(f'{p}\0{h}\n' for p, h in
                                    sorted(fingerprints.items())).encode()).hexdigest()
    require(digest == app['source_tree_sha256'], 'APPLICATION_SHA256')
    parts = json.loads((root / 'previous_parent/PARENT_PARTS.json').read_text())
    previous = manifest['previous_parent']
    require(parts['zip_sha256'] == previous['zip_sha256'] and
            parts['zip_bytes'] == previous['zip_bytes'] and
            len(parts['parts']) == previous['parts'], 'PREVIOUS_PARENT_BINDING')
    zip_hash, total = hashlib.sha256(), 0
    for index, part in enumerate(parts['parts']):
        require(part['name'] == parts['zip_file'] + f'.part{index:03d}', 'PART_ORDER')
        safe_name(part['name'])
        actual = inventories['previous_parent'][0][part['name']]
        for key in ('bytes', 'sha256', 'git_blob'):
            require(actual[key] == part[key], 'PART_' + key.upper())
        with (root / 'previous_parent' / part['name']).open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                zip_hash.update(chunk)
    require(total == previous['zip_bytes'] and zip_hash.hexdigest() == previous['zip_sha256'],
            'PREVIOUS_ZIP_SHA256')
    return {'source_composite_integrity': 'PASS', 'package': manifest['name'],
            'source_files': len(rows), 'application_files': len(fingerprints),
            'previous_parent_parts': len(parts['parts']), 'new_runtime': 'NOT_BUILT',
            'final_release': 'HOLD', 'application_executed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.manifest_sha256), sort_keys=True))
