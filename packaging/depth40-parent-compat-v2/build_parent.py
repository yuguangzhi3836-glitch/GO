"""Assemble one self-contained parent in isolated GO CI from pinned, previously tested bytes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from verify_parent import require, sha, files, safe_extract, verify_sums, source_identity, verify, restore

ROOT = Path(__file__).resolve().parent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_artifact(pins, path):
    request = urllib.request.Request(
        'https://api.github.com/repos/yuguangzhi3836-glitch/GO/actions/artifacts/'
        + str(pins['compatibility_artifact_id']) + '/zip',
        headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
                 'Accept': 'application/vnd.github+json'})
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise RuntimeError('PINNED_COMPAT_ARTIFACT_UNAVAILABLE') from None
        location = exc.headers['Location']
        require(location.startswith('https://'), 'ARTIFACT_REDIRECT_SCHEME')
        # Never forward the GitHub token to blob storage or print the signed URL.
        response = urllib.request.urlopen(location, timeout=60)
    with response, path.open('wb') as out:
        shutil.copyfileobj(response, out)
    require(sha(path) == pins['compatibility_artifact_zip_sha256'], 'COMPAT_ZIP_SHA_MISMATCH')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def commit_at(directory):
    return subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
                          check=True, capture_output=True, text=True).stdout.strip()


def main():
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('GITHUB_REPOSITORY') == 'yuguangzhi3836-glitch/GO', 'ISOLATED_GO_CI_ONLY')
    pins = json.loads((ROOT / 'PINS.json').read_text())
    canonical = Path('inputs/canonical')
    evidence = Path('inputs/compatibility')
    require(commit_at(canonical) == pins['canonical_source_commit'], 'CANONICAL_CHECKOUT_MISMATCH')
    require(commit_at(evidence) == pins['compatibility_evidence_commit'], 'EVIDENCE_CHECKOUT_MISMATCH')
    source = source_identity(canonical / 'application')
    require(all(source[k] == pins[k] for k in source), 'CANONICAL_SOURCE_MISMATCH')
    work = Path('parent-work'); work.mkdir()
    artifact = work / 'compatibility.zip'
    download_artifact(pins, artifact)
    extracted = work / 'compatibility'
    safe_extract(artifact, extracted)
    require((extracted / 'RUNTIME_MANIFEST.json').is_file(), 'COMPAT_ARTIFACT_LAYOUT')
    component_count = verify_sums(extracted)
    candidate = pins['package_candidate']
    parent = work / candidate; parent.mkdir()
    shutil.copytree(canonical / 'application', parent / 'application')
    shutil.copytree(extracted, parent / 'runtime')
    shutil.copytree(evidence / 'control-plane/depth40-compat-v2', parent / 'engineering')
    provenance = parent / 'provenance'; provenance.mkdir()
    shutil.copy2(canonical / 'docs/consolidation/CANONICAL_SOURCE_MANIFEST.json', provenance)
    shutil.copytree(evidence / 'evidence/depth40-compat-v2' / str(pins['compatibility_run_id']),
                    provenance / 'compatibility-ci')
    for name in ('PINS.json', 'README.md', 'verify_parent.py'):
        shutil.copy2(ROOT / name, parent / name)
    manifest = {**pins, 'schema_version': '1', 'package_revision': 'compat-v2-parent',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'packaging_commit': os.environ['GO_PACKAGING_SHA'], 'packaging_run_id': os.environ['GITHUB_RUN_ID'],
        'previous_parent_preserved': True, 'business_source_changed': False,
        'image_rebuilt': False, 'requires_previous_artifact_for_restore': False,
        'requires_overlay_for_restore': False, 'self_contained': True,
        'registry_repo_digest': None, 'site_binding': 'UNBOUND', 'deployment_authorized': False,
        'installed_in_hk': False, 'hk_execution': 'NOT_RUN', 'production': 'HOLD',
        'gates': {'THREE_END_REAL_UX_LOGIN': 'HOLD', 'SIX_VERTICAL_REAL_CLOSED_LOOP_E2E': 'HOLD',
                  'SEALED_NODE': 'HOLD', 'FINAL_RELEASE': 'HOLD'},
        'compatibility_validation': {'run_id': pins['compatibility_run_id'], 'unit_tests': 34,
            'docker_executor_in_unit_tests': 'SIMULATED', 'postgres_version': '18.4',
            'database_scope': 'ISOLATED_TYPE_GUARD', 'real_hk_execution': 'NOT_RUN'},
        'historical_results': [
            {'run_id': 34565938702, 'scope': '20 isolated eight-service checks of OLD runtime image',
             'reexecuted': False, 'applies_to_new_hk_runtime': False},
            {'run_id': 34571894075, 'scope': '25 isolated migration/restore checks including 14 media subchecks',
             'reexecuted': False, 'real_hk_data_restore': 'NOT_PROVEN'}],
        'identity_note': 'Package ID identifies this aggregate. Business candidate labels remain P03. '
                         'Repaired image/config and executor retain their already-tested identities.'}
    dump(parent / 'PARENT_MANIFEST.json', manifest)
    (parent / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + name + '\n' for name, p in files(parent).items()))
    checked = verify(parent)
    restored = restore(parent, work / 'restored-parent')
    delivery = Path('parent-delivery'); delivery.mkdir()
    zip_path = delivery / (candidate + '.zip')
    # Stable entry order, modes and timestamps; no credentials, symlinks or generated bytecode.
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, path in files(parent).items():
            entry = zipfile.ZipInfo(candidate + '/' + name, date_time=(2026, 9, 12, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_STORED if name.endswith('.tar.gz') else zipfile.ZIP_DEFLATED
            with path.open('rb') as src, z.open(entry, 'w', force_zip64=True) as dst:
                shutil.copyfileobj(src, dst)
    digest = sha(zip_path)
    # Verify the deliverable ZIP in a separate Python process through its documented interface.
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'verify_parent.py'), '--zip', str(zip_path),
        '--sha256', digest, '--restore-to', str(work / 'restored-from-zip')],
        check=True, capture_output=True, text=True)
    zip_result = json.loads(result.stdout)
    report = {**checked, 'created_at': datetime.now(timezone.utc).isoformat(),
        'packaging_commit': os.environ['GO_PACKAGING_SHA'], 'packaging_run_id': os.environ['GITHUB_RUN_ID'],
        'zip_file': zip_path.name, 'zip_sha256': digest, 'zip_bytes': zip_path.stat().st_size,
        'component_artifact_zip_sha256': sha(artifact), 'component_checksummed_files': component_count,
        'directory_restore': restored['restore_roundtrip'], 'zip_restore': zip_result['restore_roundtrip'],
        'fresh_checkout_commits': [pins['canonical_source_commit'], pins['compatibility_evidence_commit']],
        'packaging_ci': 'PASS', 'image_rebuilt': False, 'image_loaded': False,
        'application_tests_rerun': False, 'network_scope': 'GO repository and its fixed artifact only',
        'artifact_retention_days': 90}
    dump(delivery / 'PARENT_BUILD_REPORT.json', report)
    dump(delivery / 'VERIFY_RESULT.json', zip_result)
    shutil.copy2(parent / 'PARENT_MANIFEST.json', delivery)
    shutil.copy2(ROOT / 'verify_parent.py', delivery)
    (delivery / (zip_path.name + '.sha256')).write_text(digest + '  ' + zip_path.name + '\n')
    print('PARENT_BUILD_REPORT=' + json.dumps(report, sort_keys=True))
    print('PARENT_MANIFEST=' + json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main()
