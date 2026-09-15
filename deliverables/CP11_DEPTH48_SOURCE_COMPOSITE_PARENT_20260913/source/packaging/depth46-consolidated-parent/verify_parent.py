"""Offline verification and copy-only restoration. Never load or run an image."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
import zipfile


def require(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def files(root):
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'SYMLINK:' + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path
        else:
            require(path.is_dir(), 'SPECIAL_FILE')
    return result


def safe_name(name):
    require(name and not PurePosixPath(name).is_absolute() and
            all(p not in ('', '.', '..') for p in name.split('/')) and
            not any(c in name for c in '\\\r\n\0:'), 'UNSAFE_NAME')


def safe_extract(archive, target):
    require(not target.exists(), 'DESTINATION_EXISTS')
    with zipfile.ZipFile(archive) as z:
        seen = set()
        total = 0
        for entry in z.infolist():
            name = entry.filename.rstrip('/')
            safe_name(name)
            require(name not in seen, 'DUPLICATE_MEMBER')
            seen.add(name)
            require(stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR), 'UNSAFE_TYPE')
            total += entry.file_size
            require(total < 3_000_000_000, 'SIZE_LIMIT')
        target.mkdir()
        z.extractall(target)
        for entry in z.infolist():
            if not entry.is_dir():
                (target / entry.filename).chmod(0o755 if (entry.external_attr >> 16) & 0o111 else 0o644)


def image_identity(path, manifest):
    require(sha(path) == manifest['image_archive_sha256'], 'IMAGE_HASH')
    require(path.stat().st_size == manifest['image_archive_bytes'], 'IMAGE_BYTES')
    with tarfile.open(path, 'r:gz') as archive:
        member = archive.getmember('manifest.json')
        require(member.isfile() and member.size < 1_000_000, 'IMAGE_MANIFEST')
        items = json.load(archive.extractfile(member))
        require(len(items) == 1 and items[0]['RepoTags'] == [manifest['image_tag']], 'IMAGE_TAG')
        safe_name(items[0]['Config'])
        member = archive.getmember(items[0]['Config'])
        require(member.isfile() and member.size < 10_000_000, 'IMAGE_CONFIG')
        data = archive.extractfile(member).read()
        require('sha256:' + hashlib.sha256(data).hexdigest() == manifest['image_config_id'], 'IMAGE_ID')


def verify(root):
    actual = files(root)
    expected = json.loads((root / 'FILES_SHA256.json').read_text())
    require(set(actual) - {'FILES_SHA256.json'} == set(expected), 'PACKAGE_FILE_SET')
    for name, digest in expected.items():
        safe_name(name)
        require(sha(actual[name]) == digest, 'FILE_HASH:' + name)
    manifest = json.loads((root / 'PARENT_MANIFEST.json').read_text())
    fingerprint = {name: sha(path) for name, path in files(root / 'application').items()}
    require(fingerprint == json.loads((root / 'SOURCE_FINGERPRINT.json').read_text()), 'SOURCE_FINGERPRINT')
    tree = hashlib.sha256(''.join(f'{p}\0{h}\n' for p, h in sorted(fingerprint.items())).encode()).hexdigest()
    require(len(fingerprint) == manifest['source_files'] == 1311, 'SOURCE_COUNT')
    require(tree == manifest['source_tree_sha256'], 'SOURCE_TREE')
    baseline = json.loads((root / 'ci/retention/BASELINE.json').read_text())
    originals=baseline['original_application_git_blobs'];repairs=baseline['repaired_source_sha256']
    require(set(fingerprint)==set(originals)|set(repairs),'PARENT_RETENTION_SET')
    def git_blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    for p,digest in fingerprint.items():
        require(digest==repairs[p] if p in repairs else git_blob((root/'application'/p).read_bytes())==originals[p],'PARENT_RETENTION:'+p)
    def git_tree(directory):
        entries=[]
        for p in directory.iterdir():
            if p.is_dir():mode='40000';digest=git_tree(p);sort_key=p.name+'/'
            else:mode='100755' if p.stat().st_mode&0o111 else '100644';digest=git_blob(p.read_bytes());sort_key=p.name
            entries.append((sort_key.encode(),mode.encode()+b' '+p.name.encode()+b'\0'+bytes.fromhex(digest)))
        data=b''.join(v for k,v in sorted(entries))
        return hashlib.sha1(b'tree '+str(len(data)).encode()+b'\0'+data).hexdigest()
    require(git_tree(root/'application')==manifest['application_git_tree'],'APPLICATION_GIT_TREE')
    for name, digest in baseline['compatibility_git_blobs'].items():
        require(git_blob((root/name).read_bytes())==digest,'COMPATIBILITY_BLOB')
    supplement=root/'supplements/PR51'
    binding=json.loads((supplement/'SOURCE_BINDING.json').read_text())
    require(binding['commit']==manifest['supplement']['commit']=='a7e18cf33c0d2342a7b090fc7c61dc3290eb1d43','SUPPLEMENT_COMMIT')
    require(set(files(supplement))-{'SOURCE_BINDING.json'}==set(binding['files']),'SUPPLEMENT_FILE_SET')
    for p,row in binding['files'].items():
        f=supplement/p
        require(git_blob(f.read_bytes())==row['git_blob'] and sha(f)==row['sha256'],'SUPPLEMENT_HASH')
        require(bool(f.stat().st_mode&0o111)==(row['mode']=='100755'),'SUPPLEMENT_MODE')
    require(json.loads((supplement/'control-plane/boss-deploy-request-v1/config.json').read_text())['deployment_requests_enabled'] is False,'SUPPLEMENT_DISABLED')
    runtime = json.loads((root / 'runtime/RUNTIME_MANIFEST.json').read_text())
    for key in ('source_commit', 'source_tree_sha256', 'source_files', 'image_tag', 'image_config_id', 'image_archive_sha256', 'image_archive_bytes'):
        require(runtime[key] == manifest[key], 'RUNTIME_BINDING:' + key)
    require(sha(root / 'runtime/preflight.py') == runtime['preflight_sha256'], 'PREFLIGHT_BINDING')
    image_identity(root / 'runtime/GO_DEPTH46_CONSOLIDATED_IMAGE.tar.gz', manifest)
    require(manifest['self_contained'] is True and manifest['site_binding'] == 'UNBOUND', 'PACKAGE_STATUS')
    require(manifest['deployment_authorized'] is False and manifest['production'] == 'HOLD', 'AUTHORITY')
    return {'package_integrity': 'PASS', 'files': len(actual), 'source_commit': manifest['source_commit'],
            'source_files': len(fingerprint), 'source_tree_sha256': tree,
            'image_config_id': manifest['image_config_id'], 'offline_only': True,
            'image_loaded': False, 'deployment': 'NOT_RUN', 'final_release': 'HOLD'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--directory', type=Path)
    origin.add_argument('--zip', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--restore-to', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='go-parent-check-') as tmp:
        root = args.directory
        if args.zip:
            require(args.sha256 and sha(args.zip) == args.sha256, 'EXTERNAL_ZIP_SHA')
            extraction = Path(tmp) / 'extracted'
            safe_extract(args.zip, extraction)
            roots = list(extraction.iterdir())
            require(len(roots) == 1 and roots[0].is_dir(), 'PACKAGE_LAYOUT')
            root = roots[0]
        result = verify(root)
        if args.restore_to:
            require(not args.restore_to.exists() and not args.restore_to.is_symlink(), 'RESTORE_EXISTS')
            require(not args.restore_to.resolve().is_relative_to(root.resolve()), 'RESTORE_INSIDE_SOURCE')
            # Exclusive creation: do not replace any existing destination, even an empty one.
            args.restore_to.mkdir()
            for item in root.iterdir():
                destination = args.restore_to / item.name
                if item.is_dir():
                    shutil.copytree(item, destination)
                else:
                    shutil.copy2(item, destination)
            require(verify(args.restore_to) == result, 'RESTORE_MISMATCH')
            result['restore_roundtrip'] = 'PASS'
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
