#!/usr/bin/env python3
"""Seal/restore DEPTH25 without rewriting any earlier checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

PARENT = '8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb'
WORK = '1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79'
DEPTH24 = '6647b4c1f11e2e4fa6d39a6139089dd90c6ea68c1321c543c8a10212630ef571'
COMMIT24 = '37ef13bf65a079b19500a3a71f5d45149b09828f'


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def dump(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def load(path):
    return json.loads(Path(path).read_text())


def seal(args):
    root = args.source.resolve()
    sys.path.insert(0, str(root / 'scripts'))
    from build_review_delivery import allowed
    assert digest(args.base_work) == WORK, 'WRONG_BASE_WORK'
    assert digest(args.previous_delta) == DEPTH24, 'WRONG_DEPTH24'
    evidence = root / 'verification/current_build/depth25'
    status = load(evidence / 'CURRENT_BUILD_STATUS.json')
    assert status['python']['one_clean_full_run']
    assert status['python']['failures'] == status['python']['errors'] == 0
    assert status['remote_runtime']['runtime_acceptance'] == 'PASS'
    frozen = load(evidence / 'source_fingerprint.json')['files']
    for name, sha in frozen.items():
        assert digest(root / name) == sha, ('FROZEN_SOURCE_CHANGED', name)
    with zipfile.ZipFile(args.base_work) as z:
        before = {f['path']: f for f in json.loads(z.read('DELIVERY_FILE_MANIFEST.json'))['files']}
    with zipfile.ZipFile(args.previous_delta) as z:
        prior = json.loads(z.read('RESULT_FILE_MANIFEST.json'))['files']
    names = set(before) | {f['path'] for f in prior}
    for folder in ('src', 'frontend', 'tests', 'tests_frontend', 'scripts', 'acceptance', 'alembic'):
        names.update(p.relative_to(root).as_posix() for p in (root / folder).rglob('*') if allowed(p))
    names.update(p.relative_to(root).as_posix() for p in evidence.rglob('*') if allowed(p) and p.suffix != '.log')
    names.update(['GO_DEPTH25_START_HERE.md', 'CURRENT_DEPTH_CANDIDATE.json'])
    names.discard('DELIVERY_FILE_MANIFEST.json')
    rows, changed = [], []
    for name in sorted(names):
        p = root / name
        assert allowed(p), name
        row = {'path': name, 'size': p.stat().st_size, 'sha256': digest(p)}
        rows.append(row)
        old = before.get(name)
        if not old or old['sha256'] != row['sha256']:
            changed.append({**row, 'before_sha256': old['sha256'] if old else None, 'mode': p.stat().st_mode & 0o777})
    result = json.dumps({'status': 'ENGINEERING_REVIEW_NOT_RELEASE_ACCEPTED', 'files': rows}, ensure_ascii=False, indent=2).encode()
    change = {'build': status['build'], 'parent_sha256': PARENT, 'baseline_work_sha256': WORK,
              'previous_checkpoint_commit': COMMIT24, 'previous_delta_sha256': DEPTH24,
              'result_manifest_sha256': hashlib.sha256(result).hexdigest(),
              'FINAL_RELEASE_GATE': 'HOLD', 'preseal': False, 'removed': [], 'files': changed}
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / 'GO_CP11_DEPTH_25_POSTGRES_RUNTIME_DELTA_20260909.zip'
    assert not target.exists(), 'IMMUTABLE_OUTPUT_EXISTS'
    tmp = target.with_suffix('.building')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in changed:
            z.write(root / f['path'], 'payload/' + f['path'])
        z.writestr('DEPTH25_DELTA_MANIFEST.json', json.dumps(change, indent=2))
        z.writestr('RESULT_FILE_MANIFEST.json', result)
    with zipfile.ZipFile(tmp) as z:
        assert z.testzip() is None
        for f in changed:
            assert hashlib.sha256(z.read('payload/' + f['path'])).hexdigest() == f['sha256']
    tmp.replace(target)
    receipt = {'delta': target.name, 'size': target.stat().st_size, 'sha256': digest(target),
               'changed_files': len(changed), 'verified_source_files': len(frozen), 'result_files': len(rows),
               'previous_checkpoint_commit': COMMIT24, 'FINAL_RELEASE_GATE': 'HOLD'}
    dump(args.output / 'GO_DEPTH25_DELIVERY.json', receipt)
    print(json.dumps(receipt, indent=2))


def restore(args):
    # Reuse the previously sealed, explicit archive-path and payload validators.
    sys.path.insert(0, str(args.validator_source.resolve() / 'scripts'))
    from assemble_depth24_review import preflight, extract, verify_entries
    assert digest(args.parent) == PARENT and digest(args.base_work) == WORK, 'LOCKED_INPUT_MISMATCH'
    assert digest(args.delta) == args.expected_delta_sha256, 'DELTA_SHA256_MISMATCH'
    output = args.output.resolve()
    assert not output.exists(), 'OUTPUT_MUST_BE_NEW'
    with zipfile.ZipFile(args.parent) as parent, zipfile.ZipFile(args.base_work) as base, zipfile.ZipFile(args.delta) as delta:
        for z in (parent, base, delta):
            preflight(z)
        before = json.loads(base.read('DELIVERY_FILE_MANIFEST.json'))['files']
        change = json.loads(delta.read('DEPTH25_DELTA_MANIFEST.json'))
        result_bytes = delta.read('RESULT_FILE_MANIFEST.json')
        assert hashlib.sha256(result_bytes).hexdigest() == change['result_manifest_sha256']
        assert change['parent_sha256'] == PARENT and change['baseline_work_sha256'] == WORK
        assert change['previous_checkpoint_commit'] == COMMIT24 and change['previous_delta_sha256'] == DEPTH24
        assert not change['removed'] and not change['preseal']
        verify_entries(base, before)
        verify_entries(delta, change['files'], 'payload/')
        known = {f['path']: {k: f[k] for k in ('path', 'size', 'sha256')} for f in before}
        assert len(known) == len(before)
        for f in change['files']:
            old = known.get(f['path'])
            assert (old['sha256'] if old else None) == f['before_sha256'], f['path']
            known[f['path']] = {k: f[k] for k in ('path', 'size', 'sha256')}
        result = json.loads(result_bytes)
        expected = {f['path']: f for f in result['files']}
        assert expected == known and len(expected) == len(result['files'])
        assert set(delta.namelist()) == {'DEPTH25_DELTA_MANIFEST.json', 'RESULT_FILE_MANIFEST.json',
                                          *('payload/' + f['path'] for f in change['files'])}
        output.mkdir(parents=True)
        try:
            extract(parent, output)
            extract(base, output)
            extract(delta, output, 'payload/')
            dump(output / 'DELIVERY_FILE_MANIFEST.json', result)
            for f in result['files']:
                assert digest(output / f['path']) == f['sha256'], f['path']
            for name in ('python', 'python3', 'python3.13'):
                (output / 'gate_runtime/python/bin' / name).chmod(0o755)
            frozen = load(output / 'verification/current_build/depth25/source_fingerprint.json')['files']
            for name, sha in frozen.items():
                assert digest(output / name) == sha, name
            receipt = {'parent_sha256': PARENT, 'base_work_sha256': WORK, 'delta_sha256': digest(args.delta),
                       'verified_files': len(expected), 'verified_frozen_source_files': len(frozen),
                       'migration_head': '0132_rail_runtime_field_widths', 'FINAL_RELEASE_GATE': 'HOLD'}
            dump(output / 'DEPTH25_RESTORATION.json', receipt)
        except BaseException:
            shutil.rmtree(output)
            raise
    print(json.dumps(receipt, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('seal')
    for name in ('source', 'base-work', 'previous-delta', 'output'):
        s.add_argument('--' + name, type=Path, required=True)
    s.set_defaults(run=seal)
    r = sub.add_parser('restore')
    for name in ('validator-source', 'parent', 'base-work', 'delta', 'output'):
        r.add_argument('--' + name, type=Path, required=True)
    r.add_argument('--expected-delta-sha256', required=True)
    r.set_defaults(run=restore)
    args = p.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()
