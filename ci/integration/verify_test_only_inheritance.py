"""Fail closed before inheriting unchanged scopes of PR172's original evidence."""
import json
from pathlib import Path
import subprocess
import sys

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

plan = json.loads(Path('ci/integration/TEST_ONLY_INHERITANCE.json').read_text())
base = plan['base_commit']
assert base == '2816b75a3a9b03c5502e38a64c7d7d2fcf82eaeb'
assert git('rev-parse', base + ':application') == plan['base_application_tree']
assert git('rev-parse', 'HEAD:application') == plan['application_tree']
actual = set(git('diff', '--name-only', base, 'HEAD', '--', 'application').splitlines())
assert actual == set(plan['expected_changes']), ('UNAPPROVED_APPLICATION_DELTA', actual)
for path, blobs in plan['expected_changes'].items():
    assert path.startswith('application/tests/') and path.endswith('.py')
    assert git('rev-parse', base + ':' + path) == blobs['old_git_blob'], path
    assert git('rev-parse', 'HEAD:' + path) == blobs['new_git_blob'], path
assert git('ls-tree', '-r', '--name-only', base + ':application/tests') == git('ls-tree', '-r', '--name-only', 'HEAD:application/tests'), 'TEST_INVENTORY_CHANGED'
assert not git('diff', '--name-only', base, 'HEAD', '--',
               'ci/retention/run_suite.py', 'ci/retention/dependencies.py',
               'ci/retention/requirements.lock', 'ci/retention/guard',
               'ci/depth47', 'ci/journey-v2', 'control-plane/depth40-compat-v2'), 'RUNNER_OR_DEPENDENCIES_CHANGED'
files = sorted('tests/' + p for p in git('ls-tree', '-r', '--name-only', 'HEAD:application/tests').splitlines()
               if Path(p).name.startswith('test') and p.endswith('.py'))
affected = sorted({files.index(p.removeprefix('application/')) % 4 for p in actual})
assert affected == plan['affected_shards'] == [1, 2, 3], affected
assert plan['rerun_shards'] == [0, 1, 2, 3]
assert plan['inherited_shards'] == []
baseline = json.loads(Path('ci/retention/BASELINE.json').read_text())
assert baseline['source_tree_sha256'] == plan['source_fingerprint_sha256']
report = dict(status='PASS', candidate_sha=git('rev-parse', 'HEAD'),
              inherited_from=base, application_tree=plan['application_tree'],
              source_fingerprint_sha256=plan['source_fingerprint_sha256'],
              affected_shards=affected, rerun_shards=plan['rerun_shards'], inherited_shards=[], exact_test_blob_changes=plan['expected_changes'])
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
