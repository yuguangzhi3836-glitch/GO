"""Synthetic media preservation experiment. Not an HK import or backup executor."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from go_hotel.services.media_index import MediaIndex

assert os.environ.get('GO_DISPOSABLE_UPGRADE_CI') == 'true'
root = Path('/state/upgrade-media-ci')
root.mkdir(exist_ok=False)
checks = []
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

def record(name, ok):
    checks.append({'check': name, 'passed': bool(ok)})
    assert ok, name

def ledger(path):
    result = {}
    for p in sorted(path.rglob('*')):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            raise ValueError('MEDIA_SPECIAL_FILE_REJECTED')
        if p.is_file(): result[p.relative_to(path).as_posix()] = sha(p)
    return result

def import_copy(source, target, allow_empty=False):
    # Only CI paths; an approved operational tool must separately bind a stable real snapshot.
    assert source.parent == root and target.parent in {root, Path('/state')}
    if target.exists(): raise ValueError('TARGET_EXISTS')
    before = ledger(source)
    if 'index.json' not in before or 'index.sqlite3' in before:
        raise ValueError('LEGACY_SNAPSHOT_REQUIRED')
    data = json.loads((source/'index.json').read_text())
    records = MediaIndex.validate_snapshot(data)
    if not records and not allow_empty: raise ValueError('EMPTY_INVENTORY_REQUIRES_APPROVAL')
    for item in records.values():
        p = source/'files'/item['cache_file']
        if not p.is_file() or p.is_symlink(): raise ValueError('MISSING_MEDIA_FILE')
        if sha(p) != item.get('sha256'): raise ValueError('MEDIA_HASH_MISMATCH')
    shutil.copytree(source, target)
    (target/'files').mkdir(exist_ok=True)
    if ledger(source) != before: raise ValueError('SOURCE_CHANGED_DURING_COPY')
    index = MediaIndex(target)
    copied = index.snapshot()['assets']
    for key, old in records.items():
        got = dict(copied[key]); got.pop('revision', None)
        expected = dict(old); expected.pop('revision', None)
        if got != expected: raise ValueError('IMPORTED_RECORD_CHANGED')
    if set(copied) != set(records): raise ValueError('IMPORTED_FILE_SET_CHANGED')
    if ledger(source) != before: raise ValueError('SOURCE_MODIFIED')
    if any(sha(target/name) != digest for name,digest in before.items()):
        raise ValueError('BACKUP_FILE_NOT_PRESERVED')
    return index, before

def fixture(name, *, empty=False):
    path = root/name; (path/'files').mkdir(parents=True)
    assets = {}
    if not empty:
        for n in range(2):
            file = path/'files'/f'fixture-{n}.bin'; file.write_bytes(b'SYNTHETIC_ONLY_MEDIA_'+str(n).encode())
            assets[str(n)] = {'asset_id':str(n),'hotel_id':'ci-hotel','cache_file':file.name,
                'sha256':sha(file),'rights_status':'REVIEW_REQUIRED',
                'rights_history':[{'source':'synthetic-fixture','publishable':False}]}
        (path/'files'/'unreferenced.bin').write_bytes(b'PRESERVE_UNREFERENCED_CI_BYTES')
    (path/'index.json').write_text(json.dumps({'version':1,'assets':assets})+'\n')
    return path

def rejected(name, source, mutate, code):
    mutate(source)
    before = ledger(source)
    dest = root/(name+'-target')
    try: import_copy(source, dest)
    except (ValueError, json.JSONDecodeError) as exc:
        record(name, code in str(exc) and not dest.exists() and ledger(source)==before)
    else: record(name, False)

try:
    source = fixture('legacy')
    index, original = import_copy(source, Path('/state/media'))
    record('legacy_json_and_all_files_preserved', ledger(source)==original)
    record('rights_records_preserved_without_publishing', all(
        v['rights_status']=='REVIEW_REQUIRED' for v in index.snapshot()['assets'].values()))
    state = index.snapshot()
    record('second_open_is_idempotent', MediaIndex(Path('/state/media')).snapshot()==state)
    with sqlite3.connect(index.path) as db:
        record('schema_and_legacy_sha_bound', db.execute('SELECT schema_version,legacy_sha256 FROM media_meta').fetchall()==[(1,original['index.json'])])
        record('sqlite_integrity_check', db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
    restored = root/'sqlite-restored'; restored.mkdir()
    shutil.copytree(Path('/state/media/files'), restored/'files')
    shutil.copyfile(Path('/state/media/index.json'), restored/'index.json')
    with sqlite3.connect(index.path) as src, sqlite3.connect(restored/'index.sqlite3') as dst:
        src.backup(dst)
    record('sqlite_backup_restores_records', MediaIndex(restored).snapshot()==state)
    record('sqlite_restore_preserves_files', ledger(restored/'files')==ledger(Path('/state/media/files')))
    sys.path.insert(0,'/opt/go/staging')
    from preflight import media_gate
    os.environ['GO_MEDIA_CACHE_DIR']='/state/media'
    record('imported_volume_passes_original_read_only_media_gate', media_gate()['check_read_only'])
    rejected('missing_file_rejected', fixture('missing'), lambda p:(p/'files/fixture-0.bin').unlink(), 'MISSING_MEDIA_FILE')
    rejected('wrong_hash_rejected', fixture('hash'), lambda p:(p/'files/fixture-0.bin').write_bytes(b'CORRUPTED'), 'MEDIA_HASH_MISMATCH')
    def traversal(p):
        data=json.loads((p/'index.json').read_text()); data['assets']['0']['cache_file']='../escape.bin'
        (p/'index.json').write_text(json.dumps(data))
    rejected('path_traversal_rejected', fixture('path'), traversal, 'MEDIA_CACHE_PATH_INVALID')
    rejected('empty_inventory_requires_explicit_decision', fixture('empty',empty=True), lambda p:None, 'EMPTY_INVENTORY_REQUIRES_APPROVAL')
    empty_index, _ = import_copy(root/'empty', root/'empty-approved-ci', allow_empty=True)
    record('explicit_empty_fixture_import_is_not_media_completion', empty_index.snapshot()['assets']=={})
    try: import_copy(source, Path('/state/media'))
    except ValueError as exc: record('existing_destination_never_overwritten', str(exc)=='TARGET_EXISTS')
    else: record('existing_destination_never_overwritten',False)
    print(json.dumps({'status':'PASS_SYNTHETIC_MEDIA_ONLY','checks':checks,
        'original_ledger':original,'source_bytes_unchanged':ledger(source)==original,
        'hk_media_export_received':False,'hk_media_conversion':'NOT_RUN'},indent=2))
except BaseException:
    print(json.dumps({'status':'HOLD','checks':checks,'hk_media_conversion':'NOT_RUN'},indent=2))
    raise
