"""Verify the full DEPTH36R3 CI result and prepare immutable evidence files."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

base = Path(__file__).resolve().parent
remote = base / 'support-remote-evidence'
out = base / 'support-evidence-publication'
candidate = '7bd98db21ee950aeb91c12b296b1864b5a758c3f'
source = 'c58edb0c0568c3f9fe80ba014c260513a07a8e74b211b608ade4d9052f8645b3'
run = 34453179558

def read(path):
    return json.loads(path.read_text())

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

audit = remote / 'local-coverage'
audit.mkdir(exist_ok=True)
(audit / 'all-evidence').mkdir(exist_ok=True)
for shard in range(4):
    src = remote / 'attempt-3' / f'shard-{shard}-records'
    link = audit / 'all-evidence' / f'GO-DEPTH36-predeployment-{run}-shard-{shard}'
    if not link.exists():
        link.symlink_to(src, target_is_directory=True)
env = dict(os.environ, SEALED_CANDIDATE=candidate, EXPECTED_SOURCE_TREE=source)
subprocess.run(['python', str(base / 'acceptance-r4/ci/depth36/verify_coverage.py')],
               cwd=audit, env=env, check=True, capture_output=True, text=True)
coverage = read(audit / 'coverage.json')
jobs = read(remote / 'attempt-3/JOBS.json')['jobs']
assert len(jobs) == 5 and all(j['status'] == 'completed' and j['conclusion'] == 'success' for j in jobs)
run_metadata = read(remote / 'attempt-3/RUN.json')
assert run_metadata['id'] == run and run_metadata['conclusion'] == 'success'
assert run_metadata['head_sha'] == '9725334a729f9ea43b6cb62c63bf52539511f312'
lines = [re.sub(r'^\d{4}-\d\d-\d\dT\S+Z ', '', line)
         for line in (remote / 'attempt-3/coverage-job.log').read_text().splitlines()]
ci_coverage = []
for i, line in enumerate(lines):
    if line == '{':
        try:
            obj, _ = json.JSONDecoder().raw_decode('\n'.join(lines[i:]))
        except json.JSONDecodeError:
            continue
        if obj.get('coverage') == 'PASS':
            ci_coverage.append(obj)
assert ci_coverage == [coverage], 'CI_AND_LOCAL_COVERAGE_DIFFER'

previous_xml = base / 'remote-evidence/corrected-records/backend-full.xml'
previous = list(ET.fromstring(previous_xml.read_bytes()).iter('testcase'))
current = []
bundle_hashes = set()
for shard in range(4):
    root = remote / 'attempt-3' / f'shard-{shard}-records'
    current.extend(ET.fromstring((root / 'backend-full.xml').read_bytes()).iter('testcase'))
    lineage = read(root / 'source-lineage.json')
    assert lineage['candidate'] == candidate and lineage['source_tree_sha256'] == source
    assert lineage['verified_files'] == 1267 and lineage['node'] == 'v22.22.0'
    assert lineage['node_binary_sha256'] == '1bec56ef7cfa9a76f3e0b7c0a87f220eb73f23102b9c0b4c7529a3f7c3ce7c31'
    assert lineage['python'].startswith('3.13.5 ')
    http = read(root / 'http-result.json')
    assert http['checks_passed'] == 148 and http['failed'] == 0 and http['http_requests'] == 87
    packaging = (root / 'packaging-tests.log').read_text()
    assert re.search(r'Ran 10 tests in ', packaging) and re.search(r'^OK$', packaging, re.M)
    build = read(root / 'bundle-build.json')
    restored = read(root / 'bundle-restore.json')
    assert build == restored and build['verified_files'] == 1267
    assert build['source_tree_sha256'] == source
    bundle_hashes.add(build['archive_sha256'])
assert len(bundle_hashes) == 1

def key(case):
    return (case.get('classname'), case.get('name'))

assert Counter(map(key, previous)) == Counter(map(key, current)), 'ORIGINAL_COLLECTION_CHANGED'
current_by_key = {key(case): case for case in current}
regressions = []
for case in previous:
    if case.find('failure') is not None:
        now = current_by_key[key(case)]
        assert all(now.find(tag) is None for tag in ('failure', 'error', 'skipped'))
        regressions.append({'class': key(case)[0], 'name': key(case)[1], 'previous': 'FAIL', 'current': 'PASS'})
assert len(regressions) == 19
recent_repairs = []
for shard in range(4):
    prior = ET.fromstring((remote / 'attempt-2' / f'shard-{shard}-records/backend-full.xml').read_bytes())
    for case in prior.iter('testcase'):
        if case.find('failure') is not None:
            now = current_by_key[key(case)]
            assert all(now.find(tag) is None for tag in ('failure', 'error', 'skipped'))
            recent_repairs.append({'class': key(case)[0], 'name': key(case)[1], 'previous': 'FAIL', 'current': 'PASS'})
assert len(recent_repairs) == 5
skips = [{'class': key(case)[0], 'name': key(case)[1], 'message': case.find('skipped').get('message')}
         for case in current if case.find('skipped') is not None]
assert len(skips) == 6 and {key(c) for c in current if c.find('skipped') is not None} == {
    key(c) for c in previous if c.find('skipped') is not None}
assert coverage['collected'] == 1679 and coverage['passed'] == 1673

out.mkdir(exist_ok=True)
for attempt in ['attempt-1', 'attempt-2', 'attempt-3']:
    for path in (remote / attempt).rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(remote)
        # Preserve raw job logs as deterministic gzip; records remain byte-exact.
        if path.name.endswith('-job.log'):
            target = out / (str(relative) + '.gz')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
        elif not path.name.endswith('-job.log.gz'):
            target = out / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
for name in ['EXECUTION_BINDING.json', 'CI_TOOLING_CORRECTION.json', 'R3_CORRECTIONS.json']:
    shutil.copyfile(remote / name, out / name)
shutil.copyfile(audit / 'coverage.json', out / 'coverage.json')
shutil.copyfile(base / 'read_ci_evidence.py', out / 'read_ci_evidence.py')
shutil.copyfile(base / 'acceptance-r4/ci/depth36/verify_coverage.py', out / 'verify_coverage.py')
shutil.copyfile(Path(__file__), out / 'finalize_support_evidence.py')
save(out / 'REGRESSION_RESOLUTION.json', {
    'comparison': 'Exact multiset of original and current JUnit class/name identities',
    'original_run': 34447413327, 'original_junit_sha256': digest(previous_xml),
    'current_run': run, 'same_1679_test_identities': True, 'fixed': regressions,
    'previous_full_run': 34451882079, 'last_run_failures_resolved': recent_repairs,
    'remaining_skips': skips, 'skipped_tests_counted_as_passed': False})
status = {
    'schema': 'go.depth36r3.acceptance-status.v1',
    'repository': 'yuguangzhi3836-glitch/GO', 'candidate': candidate,
    'ci_commit': '9725334a729f9ea43b6cb62c63bf52539511f312',
    'source_tree_sha256': source, 'source_files': 1267, 'historical_support_files': 19,
    'historical_support_export': 'AUTHORIZED_AND_COMMITTED',
    'review_package_sha256': '6aac5d099e74686e89b6efef05890c986884c8efd7f89f9d781d97da2102fdd3',
    'previous_evidence_commit': '8a8a9cb070f5ee52235e2314f6b6c64912b1e10e',
    'failed_tooling_run': 34451371424, 'previous_full_run': 34451882079, 'accepted_run': run,
    'action_url': f'https://github.com/yuguangzhi3836-glitch/GO/actions/runs/{run}',
    'full_backend': 'PASS_WITH_6_POSTGRES_SKIPS', 'backend': coverage['counts'],
    'passed': coverage['passed'], 'coverage': 'EXACTLY_ONCE_ALL_1679',
    'previous_failures_resolved': 19,
    'http': {'checks_passed': 148, 'failed': 0, 'requests': 87, 'repeated_on_four_shards': True},
    'packaging': {'tests_passed': 10, 'repeated_on_four_shards': True},
    'source_after_tests': 'PASS_ALL_FOUR_SHARDS', 'source_archive_sha256': bundle_hashes.pop(),
    'three_end_real_browser': 'HOLD', 'six_vertical_real_e2e': 'HOLD',
    'postgres': 'NOT_RUN; 6 skipped tests', 'sealed_node_gate': 'HOLD',
    'native_build_and_device': 'NOT_RUN', 'provider_certification': 'NOT_RUN',
    'final_release': 'HOLD', 'merged': False, 'deployed': False}
save(out / 'STATUS.json', status)
(out / 'README.md').write_text('''# DEPTH36R3 isolated acceptance evidence

The complete SQLite backend collection passed: 1,673 passed, 6 PostgreSQL tests skipped, no failures or errors. All 1,679 original test identities are preserved and assigned to exactly one of four shards. The 19 failures from the previous full run now pass individually.

Candidate: `7bd98db21ee950aeb91c12b296b1864b5a758c3f` (1,267 source files). CI: `9725334a729f9ea43b6cb62c63bf52539511f312`. Accepted run: [34453179558](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558), draft [PR #20](https://github.com/yuguangzhi3836-glitch/GO/pull/20).

Each shard also passed the same 148 live loopback HTTP checks (87 requests), 10 packaging safeguards, independent bundle restoration, and unchanged-source verification. Repeated checks are not added together as distinct test coverage. Python 3.13.5 and Node 22.22.0 are recorded with the Node binary hash; the separately sealed Node gate remains open.

The user explicitly authorized the 19 historical support files and source fingerprints in the review package. They are restored byte-for-byte from the documented historical archive and included in candidate package `deliverables/CP11_DEPTH36R2_SUPPORT_RESTORE_20260910`. Historical deployment/governance documents are provenance, not evidence of a current Hong Kong deployment. The previous blocked review remains preserved as approval history.

`attempt-1` preserves the collection failure. `attempt-2` preserves the complete 1,668-pass / 5-fail / 6-skip run. `CI_TOOLING_CORRECTION.json` and `R3_CORRECTIONS.json` explain the source-root import, guarded process entry and mobile contract repairs. `attempt-3` preserves the final raw job logs as deterministic gzip and the original exported records. Candidate package `deliverables/CP11_DEPTH36R3_MOBILE_CONTRACT_20260910` changes only the existing mobile release test, while inheriting all 19 authorized support files unchanged. `EXTRACTION_VERIFICATION.json` files bind each recovered record to its byte count and SHA-256. `coverage.json` is verified equal to the CI coverage output. `REGRESSION_RESOLUTION.json` binds every old failure to its current passing result. Artifact IDs, archive digests and expiration dates are recorded alongside each run.

Previous evidence remains at [8a8a9cb](https://github.com/yuguangzhi3836-glitch/GO/tree/8a8a9cb070f5ee52235e2314f6b6c64912b1e10e/deliverables/CP11_DEPTH36_ACCEPTANCE_20260910). This status supersedes its open support-export and full-backend failure status for this new candidate. The candidate package's original PENDING release record is preserved as the pre-run snapshot; STATUS.json here is the post-run acceptance record bound to that immutable candidate.

Final release remains HOLD. Real-browser three-surface and six-vertical E2E, PostgreSQL, native build/device, sealed Node runtime and provider certification gates are not closed by this run. No merge, deployment or live database operation was performed.
''')
save(out / 'SHA256SUMS.json', {str(p.relative_to(out)): {'bytes': p.stat().st_size, 'sha256': digest(p)}
    for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS.json'})
print(json.dumps(status, indent=2))
