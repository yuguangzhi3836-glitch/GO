"""Bind isolated acceptance to retained parent bytes and explicit revisions."""
import base64
import hashlib
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'application'
EVIDENCE = ROOT / 'journey-evidence'
EVIDENCE.mkdir(exist_ok=True)
BASE = 'b5732c02dd95092a63def7eaa0d2cf332b1e2996'
BASE_TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def tree(fp):
    return digest(''.join(f'{p}\0{h}\n' for p, h in sorted(fp.items())).encode())

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

old = {}
for record in git('ls-tree', '-r', '-z', BASE, 'application').split(b'\0'):
    if not record:
        continue
    meta, path = record.split(b'\t')
    mode, kind, sha = meta.split()
    assert kind == b'blob' and mode in {b'100644', b'100755'}, record
    old[path.decode()[len('application/'):]] = digest(git('cat-file', 'blob', sha.decode()))
assert len(old) == 1271 and tree(old) == BASE_TREE, 'FROZEN_PARENT_SOURCE_MISMATCH'
expected = dict(old)
restored = []
for name in ('delta36', 'delta37'):
    delta = json.loads((ROOT / 'ci' / 'journey' / 'retention' / f'{name}.json').read_text())
    for rel, encoded in delta.items():
        content = base64.b64decode(encoded, validate=True)
        expected[rel] = digest(content)
        restored.append({'path': rel, 'revision': name, 'parent_sha256': old.get(rel), 'restored_sha256': digest(content)})
current = {p.relative_to(SOURCE).as_posix(): digest(p.read_bytes()) for p in SOURCE.rglob('*') if p.is_file()}
assert not any(p.is_symlink() for p in SOURCE.rglob('*')), 'SOURCE_SYMLINK'
changes = json.loads((ROOT / 'ci' / 'journey' / 'business-fixes.json').read_text())
for rel, change in changes.items():
    assert expected.get(rel) == change['before_sha256'], 'REPAIR_PARENT_MISMATCH:' + rel
    expected[rel] = change['after_sha256']
assert current == expected, 'UNDECLARED_SOURCE_CHANGE:' + repr(sorted(p for p in set(current) | set(expected) if current.get(p) != expected.get(p)))
fp = EVIDENCE / 'source-fingerprint.json'
fp.write_text(json.dumps(current, indent=2) + '\n')
report = {'candidate': 'CP11_DEPTH41_JOURNEY_RETENTION_20260912',
    'parent_package': 'CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912',
    'parent_zip_sha256': '421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a',
    'canonical_parent_commit': BASE, 'parent_source_tree_sha256': BASE_TREE,
    'candidate_commit': git('rev-parse', 'HEAD').decode().strip(),
    'source_tree_sha256': tree(current), 'source_files': len(current),
    'retained_parent_files': len(old), 'restored_revisions': restored,
    'business_fixes': changes, 'source_integrity': 'PASS',
    'compatibility_component_commit': 'd49465a56a7768bc4e657858272a597c5d1f05d6',
    'runtime_image_reused_for_new_source': False, 'hong_kong': 'NOT_RUN', 'production': 'HOLD'}
(EVIDENCE / 'source-binding.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
