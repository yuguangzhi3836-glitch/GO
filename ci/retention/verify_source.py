"""Verify the exact integrated candidate while preserving all inherited PASS bytes."""
import hashlib
import json
import pathlib
import subprocess
import sys
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / 'application'

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

def main():
    current = json.loads((ROOT/'ci/retention/BASELINE.json').read_text())
    inherited_path = ROOT/current['inherited_manifest']['path']
    assert blob(inherited_path.read_bytes()) == current['inherited_manifest']['git_blob'], 'INHERITED_BASELINE_CHANGED'
    inherited = json.loads(inherited_path.read_text())
    original = inherited['original_application_git_blobs']
    repairs = inherited['repaired_source_sha256']
    overrides = current['approved_application_overrides']
    expected = set(original) | set(repairs) | set(overrides)
    tracked = git('ls-files','-z','application').split('\0')
    actual = {p[len('application/'):] for p in tracked if p}
    assert actual == expected, {'missing': sorted(expected-actual), 'unexpected': sorted(actual-expected)}
    assert git('rev-parse','HEAD:application') == current['application_git_tree'], 'WRONG_APPLICATION_TREE'
    fingerprint = {}
    for path in sorted(expected):
        f = APP/path
        assert not f.is_symlink(), path
        data = f.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if path in overrides:
            assert blob(data) == overrides[path]['git_blob'], 'APPROVED_OVERRIDE_MISMATCH:' + path
        elif path in repairs:
            assert digest == repairs[path], 'REPAIR_MISMATCH:' + path
        else:
            assert blob(data) == original[path], 'INHERITED_SOURCE_CHANGED:' + path
        fingerprint[path] = digest
    for path, digest in inherited['compatibility_git_blobs'].items():
        assert blob((ROOT/path).read_bytes()) == digest, 'COMPATIBILITY_CHANGED:' + path
    migration_path = APP/current['migration_file']
    migration = migration_path.read_text()
    assert re.search(r"^revision\s*=\s*['\"]" + re.escape(current['migration_head']) + r"['\"]", migration, re.M), 'WRONG_MIGRATION_HEAD'
    assert current['migration_head'] == '0138_supplier_library_import'
    assert re.search(r"^down_revision\s*=\s*['\"]0137_hosted_unknown_episode['\"]", migration, re.M)
    model=(APP/'src/go_hotel/db/models.py').read_text()
    assert 'status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)' in model
    tree = hashlib.sha256(''.join(f'{p}\0{h}\n' for p,h in sorted(fingerprint.items())).encode()).hexdigest()
    assert tree == current['source_tree_sha256'], 'WRONG_SOURCE_FINGERPRINT'
    out=pathlib.Path(sys.argv[1]).resolve()
    assert APP not in out.parents and out != APP
    out.mkdir(parents=True,exist_ok=True)
    (out/'SOURCE_FINGERPRINT.json').write_text(json.dumps(fingerprint,indent=2)+'\n')
    report={'product_candidate_commit':current['product_candidate_commit'],'gate_commit':git('rev-parse','HEAD'),
            'application_tree':current['application_git_tree'],'source_files':len(expected),'source_tree_sha256':tree,
            'inherited_baseline_blob':current['inherited_manifest']['git_blob'],'approved_overrides':sorted(overrides),
            'migration_head':current['migration_head'],'byte_retention':'PASS','deployment':'NOT_RUN',
            'final_release':'HOLD','production':'HOLD'}
    (out/'RETENTION_RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':
    main()
