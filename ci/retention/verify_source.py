"""Verify the repaired checkout against frozen source and per-file repair provenance."""
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / 'application'

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def main():
    manifest = json.loads((ROOT / 'ci/retention/BASELINE.json').read_text())
    original = manifest['original_application_git_blobs']
    repairs = manifest['repaired_source_sha256']
    expected = set(original) | set(repairs)
    tracked = subprocess.check_output(['git', 'ls-files', '-z', 'application'], cwd=ROOT).decode().split('\0')
    actual = {p[len('application/'):] for p in tracked if p}
    assert actual == expected, {'missing': sorted(expected-actual), 'unexpected': sorted(actual-expected)}
    fingerprint = {}
    for path in sorted(expected):
        f = APP / path
        assert not f.is_symlink(), path
        data = f.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if path in repairs:
            assert digest == repairs[path], 'REPAIR_MISMATCH:' + path
        else:
            assert blob(data) == original[path], 'INHERITED_SOURCE_CHANGED:' + path
        fingerprint[path] = digest
    for path, digest in manifest['compatibility_git_blobs'].items():
        assert blob((ROOT/path).read_bytes()) == digest, 'COMPATIBILITY_CHANGED:' + path
    tree = hashlib.sha256(''.join(f'{p}\0{h}\n' for p,h in sorted(fingerprint.items())).encode()).hexdigest()
    out = pathlib.Path(sys.argv[1]).resolve()
    assert APP not in out.parents and out != APP
    out.mkdir(parents=True, exist_ok=True)
    (out/'SOURCE_FINGERPRINT.json').write_text(json.dumps(fingerprint, indent=2)+'\n')
    report = {'source_files': len(expected), 'source_tree_sha256':tree,
              'unchanged_parent_files': len(set(original)-set(repairs)),
              'new_files':len(set(repairs)-set(original)),
              'repaired_existing_files':len(set(repairs)&set(original)),
              'compatibility_files_unchanged':len(manifest['compatibility_git_blobs']),
              'checkpoint_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
              'byte_retention':'PASS', 'full_feature_retention':'HOLD_APPROVAL_BLOCKED_PROVIDER_GUARD',
              'deployment':'NOT_RUN','production':'HOLD'}
    (out/'RETENTION_RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__ == '__main__':
    main()
