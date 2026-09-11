"""Offline parent verification and copy-only restoration; never loads or runs an image."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile


def require(condition, code):
    if not condition:
        raise ValueError(code)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def files(root):
    require(root.is_dir() and not root.is_symlink(), 'INVALID_ROOT')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'SYMLINK_NOT_ALLOWED')
        if path.is_dir():
            continue
        require(path.is_file(), 'NON_REGULAR_FILE')
        result[path.relative_to(root).as_posix()] = path
    return dict(sorted(result.items()))


def safe_name(name):
    path = PurePosixPath(name)
    require(bool(name) and not path.is_absolute() and '\\' not in name
            and ':' not in name and not any(c in name for c in '\r\n\0')
            and all(p not in ('', '.', '..') for p in name.split('/')), 'UNSAFE_PATH')
    return path


def verify_sums(root):
    actual = files(root)
    require('SHA256SUMS' in actual, 'MISSING_SHA256SUMS')
    expected = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        require(re.fullmatch(r'[0-9a-f]{64}  .+', line) is not None, 'INVALID_CHECKSUM_LINE')
        digest, name = line.split('  ', 1)
        safe_name(name)
        require(name != 'SHA256SUMS' and name not in expected, 'DUPLICATE_CHECKSUM')
        expected[name] = digest
    require(set(actual) - {'SHA256SUMS'} == set(expected), 'FILE_SET_MISMATCH')
    for name, digest in expected.items():
        require(sha(actual[name]) == digest, 'FILE_HASH_MISMATCH:' + name)
    return len(expected)


def source_identity(root):
    tree = hashlib.sha256()
    mapping = files(root)
    for name, path in mapping.items():
        safe_name(name)
        tree.update((name + '\0' + sha(path) + '\n').encode())
    return {'source_files': len(mapping), 'source_tree_sha256': tree.hexdigest()}


def safe_extract(archive, target):
    require(not target.exists(), 'EXTRACT_TARGET_EXISTS')
    with zipfile.ZipFile(archive) as z:
        seen = set()
        total = 0
        for entry in z.infolist():
            name = entry.filename.rstrip('/') if entry.is_dir() else entry.filename
            safe_name(name)
            require(name not in seen, 'DUPLICATE_ARCHIVE_MEMBER')
            seen.add(name)
            mode = entry.external_attr >> 16
            require(not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'UNSAFE_ARCHIVE_TYPE')
            total += entry.file_size
            require(total < 2_000_000_000, 'ARCHIVE_SIZE_LIMIT')
        target.mkdir()
        z.extractall(target)


def image_identity(path, pins):
    require(path.stat().st_size == pins['image_archive_bytes'], 'IMAGE_SIZE_MISMATCH')
    require(sha(path) == pins['image_archive_sha256'], 'IMAGE_HASH_MISMATCH')
    with tarfile.open(path, 'r:gz') as image:
        manifest_member = image.getmember('manifest.json')
        require(manifest_member.isfile() and manifest_member.size < 1_000_000, 'IMAGE_MANIFEST_TYPE')
        manifest = json.load(image.extractfile(manifest_member))
        require(len(manifest) == 1, 'IMAGE_MANIFEST_COUNT')
        require(manifest[0]['RepoTags'] == [pins['image_tag']], 'IMAGE_TAG_MISMATCH')
        config_name = manifest[0]['Config']
        safe_name(config_name)
        config_member = image.getmember(config_name)
        require(config_member.isfile() and config_member.size < 10_000_000, 'IMAGE_CONFIG_TYPE')
        config_bytes = image.extractfile(config_member).read()
        image_id = 'sha256:' + hashlib.sha256(config_bytes).hexdigest()
        require(image_id == pins['image_config_id'], 'IMAGE_CONFIG_ID_MISMATCH')
    return image_id


def verify(root):
    count = verify_sums(root)
    pins = json.loads((root / 'PINS.json').read_text())
    parent = json.loads((root / 'PARENT_MANIFEST.json').read_text())
    for key, value in pins.items():
        require(parent.get(key) == value, 'PARENT_PIN_MISMATCH:' + key)
    source = source_identity(root / 'application')
    for key, value in source.items():
        require(value == pins[key], 'SOURCE_MISMATCH:' + key)
    runtime = root / 'runtime'
    verify_sums(runtime)
    meta = json.loads((runtime / 'RUNTIME_MANIFEST.json').read_text())
    for key in ('image_tag', 'image_config_id', 'image_archive_sha256', 'image_archive_bytes',
                'source_tree_sha256', 'source_files', 'preflight_sha256'):
        require(meta[key] == pins[key], 'RUNTIME_PIN_MISMATCH:' + key)
    require(meta['tooling_commit'] == pins['compatibility_commit'], 'RUNTIME_COMMIT_MISMATCH')
    require(meta['ci_run_id'] == str(pins['compatibility_run_id']), 'RUNTIME_RUN_MISMATCH')
    require(meta['parent_candidate'] == pins['business_candidate'], 'BUSINESS_PARENT_MISMATCH')
    require(meta['image_build'] == meta['offline_reload'] == 'PASS', 'RUNTIME_BUILD_NOT_PASSED')
    require(json.loads((runtime / 'GATE_REPORT.json').read_text())['ci_status'] == 'success', 'COMPAT_CI_NOT_SUCCESS')
    executor = json.loads((runtime / 'EXECUTOR_MANIFEST.json').read_text())
    require(executor['site_binding'] == 'UNBOUND' and executor['installed'] is False, 'UNEXPECTED_INSTALLATION')
    require(set(executor['files']) == set('executor/' + p for p in files(runtime / 'executor')), 'EXECUTOR_FILE_SET')
    for name, digest in executor['files'].items():
        safe_name(name)
        require(sha(runtime / name) == digest, 'EXECUTOR_HASH_MISMATCH')
        require(sha(root / 'engineering' / name) == digest, 'ENGINEERING_EXECUTOR_MISMATCH')
    require(sha(root / 'engineering/image/preflight.py') == pins['preflight_sha256'], 'PREFLIGHT_MISMATCH')
    require(sha(root / 'engineering/compose.staging.review.yml') == sha(runtime / 'compose.staging.review.yml'), 'COMPOSE_MISMATCH')
    image_id = image_identity(runtime / 'GO_DEPTH40_COMPAT_IMAGE.tar.gz', pins)
    require(parent['self_contained'] is True and parent['site_binding'] == 'UNBOUND', 'PARENT_STATE')
    require(parent['deployment_authorized'] is False and parent['production'] == 'HOLD', 'AUTHORITY_STATE')
    return {'package_candidate': pins['package_candidate'], 'package_integrity': 'PASS',
            'checksummed_files': count, **source, 'image_config_id': image_id,
            'image_archive_sha256': pins['image_archive_sha256'],
            'executor_identity': 'PASS', 'network_used': False, 'image_loaded': False,
            'hk_execution': 'NOT_RUN', 'deployment': 'HOLD', 'production': 'HOLD'}


def restore(source, target, verifier=verify):
    """Validate, then copy into a new path only. Never alter an existing destination."""
    result = verifier(source)
    require(not target.exists() and not target.is_symlink(), 'RESTORE_TARGET_EXISTS')
    require(target.parent.is_dir(), 'RESTORE_PARENT_MISSING')
    require(not target.resolve().is_relative_to(source.resolve()), 'RESTORE_INSIDE_SOURCE')
    with tempfile.TemporaryDirectory(prefix='.go-parent-restore-', dir=target.parent) as tmp:
        staging = Path(tmp) / 'payload'
        shutil.copytree(source, staging)
        require(verifier(staging) == result, 'RESTORE_VERIFICATION_MISMATCH')
        # mkdir is exclusive, so even an empty destination is not overwritten.
        target.mkdir()
        try:
            for item in staging.iterdir():
                item.rename(target / item.name)
        except BaseException:
            # Never delete a destination on failure. Leave partial output visible for review.
            raise
    return {**result, 'restore_roundtrip': 'PASS', 'restored_to': str(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--directory', type=Path)
    origin.add_argument('--zip', type=Path)
    parser.add_argument('--sha256', help='Required external trust anchor when --zip is used')
    parser.add_argument('--restore-to', type=Path, help='New destination only; copy files without executing anything')
    args = parser.parse_args()
    if args.directory:
        result = restore(args.directory, args.restore_to) if args.restore_to else verify(args.directory)
    else:
        require(args.sha256 and re.fullmatch('[0-9a-f]{64}', args.sha256), 'EXTERNAL_ZIP_SHA_REQUIRED')
        require(sha(args.zip) == args.sha256, 'PARENT_ZIP_SHA_MISMATCH')
        with tempfile.TemporaryDirectory(prefix='go-parent-verify-') as tmp:
            extraction = Path(tmp) / 'extracted'
            safe_extract(args.zip, extraction)
            roots = list(extraction.iterdir())
            require(len(roots) == 1 and roots[0].is_dir(), 'PARENT_ZIP_LAYOUT')
            result = restore(roots[0], args.restore_to) if args.restore_to else verify(roots[0])
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
