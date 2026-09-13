"""Build the unified parent in isolated GO CI. No deployment or external business operations."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from verify_parent import require, sha, files, safe_extract, verify

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NAME = 'CP11_DEPTH41_UNIFIED_PARENT_V1_20260912'
OLD_COMMIT = 'b65a07c2aea9ac1e79013540d9cf28a69a190935'
OLD_NAME = 'CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912'
OLD_SHA = '421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a'
OLD_IMAGE = 'sha256:cba95a5ac6f061b8196f953f181952fdad94ab520a12cbeb0e7ee49d9a6de150'
OLD_TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'
APP_TREE = 'a73b9b53a59c88ab995d0f9b123c9fb79e87e60d'


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, capture_output=True, text=True, **kwargs).stdout.strip()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def preserve_browser_zip(parent):
    """Read one fixed GO artifact; never forward Authorization to its storage redirect."""
    out = parent / 'evidence/canonical-alignment/pr48-c8d2b802'
    expected = '8d131808c3e8db45918060c7efc98211db7119f71d2974cce75a1aee61c5b322'
    target = out / 'ORIGINAL_BROWSER_ARTIFACT.zip'
    request = urllib.request.Request('https://api.github.com/repos/yuguangzhi3836-glitch/GO/actions/artifacts/10288988013/zip',
        headers={'Authorization': 'Bearer ' + os.environ['GO_READ_TOKEN'], 'Accept': 'application/vnd.github+json'})
    try:
        try:
            response = urllib.request.build_opener(NoRedirect).open(request, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise
            location = exc.headers['Location']
            require(location.startswith('https://'), 'ARTIFACT_REDIRECT')
            response = urllib.request.urlopen(location, timeout=60)
        with response, target.open('xb') as stream:
            shutil.copyfileobj(response, stream)
        require(sha(target) == expected, 'ORIGINAL_ARTIFACT_HASH')
        with zipfile.ZipFile(target) as archive:
            require(archive.testzip() is None, 'ORIGINAL_ARTIFACT_CRC')
        result = {'status': 'ARCHIVED_HASH_VERIFIED', 'artifact_id': 10288988013,
                  'source_commit': 'c8d2b8021dce80388b8f548257db6a86d227c98a',
                  'sha256': expected, 'bytes': target.stat().st_size, 'historical_only': True,
                  'visual_review_performed': False, 'pass_transferred': False}
    except (urllib.error.URLError, TimeoutError) as exc:
        target.unlink(missing_ok=True)
        result = {'status': 'HOLD_DOWNLOAD', 'error_type': type(exc).__name__, 'artifact_id': 10288988013}
    dump(out / 'ARCHIVE_RECEIPT.json', result)
    return result


def main():
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REPOSITORY') == 'yuguangzhi3836-glitch/GO', 'GO_CI_ONLY')
    commit = run('git', 'rev-parse', 'HEAD', cwd=ROOT)
    require(commit == os.environ['GO_SOURCE_SHA'] and run('git', 'rev-parse', 'HEAD:application', cwd=ROOT) == APP_TREE, 'EXACT_CANDIDATE')
    work = Path(os.environ['RUNNER_TEMP']) / 'unified-parent-work'
    work.mkdir()
    checks = work / 'source-checks'
    run(sys.executable, '-B', str(ROOT / 'ci/retention/verify_source.py'), str(checks))
    run(sys.executable, '-B', str(ROOT / 'ci/retention/verify_alignment.py'), str(checks / 'ALIGNMENT_RESULT.json'))
    retention = json.loads((checks / 'RETENTION_RESULT.json').read_text())
    tree = retention['source_tree_sha256']
    old_repo = ROOT / 'inputs/previous-parent'
    require(run('git', 'rev-parse', 'HEAD', cwd=old_repo) == OLD_COMMIT, 'OLD_ARCHIVE_COMMIT')
    old_directory = old_repo / 'deliverables' / OLD_NAME
    old_zip = work / (OLD_NAME + '.zip')
    run(sys.executable, '-B', str(old_directory / 'reconstruct_parent.py'), '--directory', str(old_directory), '--output', str(old_zip))
    require(sha(old_zip) == OLD_SHA, 'OLD_PARENT_SHA')
    old_check = json.loads(run(sys.executable, '-B', str(old_directory / 'verify_parent.py'), '--zip', str(old_zip), '--sha256', OLD_SHA))
    extraction = work / 'old-parent'
    safe_extract(old_zip, extraction)
    old = extraction / OLD_NAME
    old_manifest = json.loads((old / 'PARENT_MANIFEST.json').read_text())
    require(old_manifest['image_config_id'] == OLD_IMAGE, 'OLD_IMAGE_PIN')
    with gzip.open(old / 'runtime/GO_DEPTH40_COMPAT_IMAGE.tar.gz', 'rb') as stream:
        subprocess.run(['docker', 'load'], stdin=stream, check=True, stdout=subprocess.PIPE)
    base_tag = old_manifest['image_tag']
    require(run('docker', 'image', 'inspect', base_tag, '--format', '{{.Id}}') == OLD_IMAGE, 'LOADED_BASE_ID')
    source_check = json.loads(run('docker', 'run', '--rm', '--network', 'none', '--read-only', base_tag, 'source-check'))
    require(source_check['source_tree_sha256'] == OLD_TREE and source_check['files'] == 1271, 'BASE_SOURCE')
    parent = work / NAME
    parent.mkdir()
    selected_prefixes = ('application/', 'control-plane/depth40-compat-v2/', 'ci/', 'docs/', 'evidence/canonical-alignment/', 'packaging/depth41-unified-parent/')
    selected_roots = {'AGENTS.md', 'README.md', 'GO_REPOSITORY_INDEX.md', '.github/workflows/canonical-parent-retention.yml', '.github/workflows/canonical-mobile-retention.yml'}
    tracked = run('git', 'ls-files', '-z', cwd=ROOT).split('\0')
    for name in sorted(p for p in tracked if p and (p.startswith(selected_prefixes) or p in selected_roots)):
        source = ROOT / name
        require(not source.is_symlink(), 'SOURCE_SYMLINK')
        target = parent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(checks / 'SOURCE_FINGERPRINT.json', parent)
    shutil.copytree(checks, parent / 'evidence/current-source')
    provenance = parent / 'provenance'
    provenance.mkdir()
    shutil.copy2(old / 'PARENT_MANIFEST.json', provenance / 'PREVIOUS_PARENT_MANIFEST.json')
    dump(provenance / 'PREVIOUS_PARENT_VERIFICATION.json', old_check)
    browser_archive = preserve_browser_zip(parent)
    context = work / 'image-context'
    context.mkdir()
    shutil.copytree(parent / 'application', context / 'application')
    shutil.copy2(parent / 'SOURCE_FINGERPRINT.json', context)
    original = (ROOT / 'control-plane/depth40-compat-v2/image/preflight.py').read_text()
    require(original.count(OLD_TREE) == 1 and original.count('len(actual) != 1271') == 1, 'PREFLIGHT_IDENTITY_PATTERN')
    generated = original.replace(OLD_TREE, tree).replace('len(actual) != 1271', 'len(actual) != 1300')
    (context / 'preflight.py').write_text(generated)
    tag = 'go-depth41-unified:pr47-' + commit[:12]
    (context / 'Dockerfile').write_text('FROM ' + base_tag + '\nCOPY application/ /opt/go/source/\nCOPY SOURCE_FINGERPRINT.json /opt/go/SOURCE_FINGERPRINT.json\nCOPY preflight.py /opt/go/staging/preflight.py\nLABEL org.opencontainers.image.revision="' + commit + '" go.source.tree="' + tree + '" go.package="' + NAME + '"\n')
    runtime = parent / 'runtime'
    runtime.mkdir()
    (runtime / 'BUILD.log').write_text(run('docker', 'build', '--network', 'none', '--pull=false', '--tag', tag, str(context)) + '\n')
    image_id = run('docker', 'image', 'inspect', tag, '--format', '{{.Id}}')
    require(image_id != OLD_IMAGE, 'NEW_IMAGE_ID_REQUIRED')
    image_check = json.loads(run('docker', 'run', '--rm', '--network', 'none', '--read-only', tag, 'source-check'))
    require(image_check['source_tree_sha256'] == tree and image_check['files'] == 1300, 'IMAGE_SOURCE_BINDING')
    dump(runtime / 'SOURCE_CHECK.json', image_check)
    frozen = dict(line.strip().split('==') for line in (ROOT / 'ci/retention/requirements.lock').read_text().splitlines() if line.strip())
    script = 'import importlib.metadata as m,json; expected=' + repr(frozen) + '; actual={k:m.version(k) for k in expected}; assert actual==expected,(actual,expected); print(json.dumps(actual,sort_keys=True))'
    installed = json.loads(run('docker', 'run', '--rm', '--network', 'none', '--read-only', '--entrypoint', '/opt/go/python/bin/python3.13', tag, '-B', '-c', script))
    dump(runtime / 'DEPENDENCY_VERSIONS.json', installed)
    image_preflight = run('docker', 'run', '--rm', '--network', 'none', '--read-only', '--entrypoint', '/opt/go/python/bin/python3.13', tag, '-B', '-c', "import hashlib;print(hashlib.sha256(open('/opt/go/staging/preflight.py','rb').read()).hexdigest())")
    require(image_preflight == sha(context / 'preflight.py'), 'IMAGE_PREFLIGHT')
    for name in ('Dockerfile', 'preflight.py'):
        shutil.copy2(context / name, runtime)
    tar = runtime / 'GO_DEPTH41_UNIFIED_IMAGE.tar.gz'
    with tar.open('xb') as stream:
        save = subprocess.Popen(['docker', 'save', tag], stdout=subprocess.PIPE)
        with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0, filename='') as target:
            shutil.copyfileobj(save.stdout, target)
        require(save.wait() == 0, 'IMAGE_SAVE')
    run('docker', 'image', 'rm', tag)
    with gzip.open(tar, 'rb') as stream:
        subprocess.run(['docker', 'load'], stdin=stream, check=True, stdout=subprocess.PIPE)
    require(run('docker', 'image', 'inspect', tag, '--format', '{{.Id}}') == image_id, 'OFFLINE_RELOAD')
    reloaded = json.loads(run('docker', 'run', '--rm', '--network', 'none', '--read-only', tag, 'source-check'))
    require(reloaded == image_check, 'RELOADED_SOURCE')
    manifest = {'schema_version': 1, 'package_candidate': NAME, 'status': 'UNIQUE_PARENT_PENDING_ACCEPTANCE',
        'source_commit': commit, 'application_git_tree': APP_TREE, 'source_tree_sha256': tree, 'source_files': 1300,
        'image_tag': tag, 'image_config_id': image_id, 'image_archive_sha256': sha(tar), 'image_archive_bytes': tar.stat().st_size,
        'previous_parent_commit': OLD_COMMIT, 'previous_parent_zip_sha256': OLD_SHA, 'previous_parent_preserved': True,
        'previous_image_config_id': OLD_IMAGE, 'image_rebuilt': True, 'image_source_check': 'PASS', 'offline_image_reload': 'PASS',
        'runtime_dependencies_match_regression_lock': True, 'preflight_sha256': image_preflight,
        'preflight_change': 'source identity only; all compatibility/config/database/permission checks retained',
        'compatibility_files_preserved': 19, 'self_contained': True, 'requires_previous_artifact_for_restore': False,
        'requires_overlay_for_restore': False, 'browser_historical_archive': browser_archive,
        'build_run_id': os.environ['GITHUB_RUN_ID'], 'application_regression': 'SEE_EXACT_SOURCE_RUN',
        'site_binding': 'UNBOUND', 'deployment_authorized': False, 'hk_execution': 'NOT_RUN', 'production': 'HOLD',
        'gates': {'FULL_THREE_END_UX': 'HOLD', 'SIX_VERTICAL_CLOSED_LOOP': 'HOLD', 'SEALED_NODE': 'HOLD', 'FINAL_RELEASE': 'HOLD'}}
    dump(runtime / 'RUNTIME_MANIFEST.json', manifest)
    dump(parent / 'PARENT_MANIFEST.json', manifest)
    shutil.copy2(HERE / 'verify_parent.py', parent)
    shutil.copy2(HERE / 'README.md', parent / 'START_HERE.md')
    dump(parent / 'FILES_SHA256.json', {name: sha(path) for name, path in files(parent).items()})
    checked = verify(parent)
    delivery = ROOT / 'parent-delivery'
    delivery.mkdir()
    zip_path = delivery / (NAME + '.zip')
    with zipfile.ZipFile(zip_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in files(parent).items():
            entry = zipfile.ZipInfo(NAME + '/' + name, date_time=(2026, 9, 12, 0, 0, 0))
            entry.external_attr = (0o100755 if path.stat().st_mode & 0o111 else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_STORED if name.endswith(('.tar.gz', '.zip')) or '/dependency_parts/' in name else zipfile.ZIP_DEFLATED
            with path.open('rb') as source, archive.open(entry, 'w', force_zip64=True) as target:
                shutil.copyfileobj(source, target)
    digest = sha(zip_path)
    restored = json.loads(run(sys.executable, '-B', str(HERE / 'verify_parent.py'), '--zip', str(zip_path), '--sha256', digest, '--restore-to', str(work / 'restored-new-parent')))
    report = {**checked, 'zip_file': zip_path.name, 'zip_bytes': zip_path.stat().st_size, 'zip_sha256': digest,
              'zip_restore': restored['restore_roundtrip'], 'image_rebuilt': True, 'offline_image_reload': 'PASS',
              'image_source_check': 'PASS', 'runtime_dependencies_match_regression_lock': True, 'build_run_id': os.environ['GITHUB_RUN_ID']}
    dump(delivery / 'PARENT_BUILD_REPORT.json', report)
    shutil.copy2(parent / 'PARENT_MANIFEST.json', delivery)
    shutil.copy2(HERE / 'verify_parent.py', delivery)
    (delivery / (zip_path.name + '.sha256')).write_text(digest + '  ' + zip_path.name + '\n')
    print('PARENT_BUILD_REPORT=' + json.dumps(report, sort_keys=True))
    print('PARENT_MANIFEST=' + json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main()
