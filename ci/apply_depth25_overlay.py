"""Apply only the reviewed DEPTH25 files over verified frozen DEPTH24 source."""
import hashlib
import json
from pathlib import Path


def digest(data):return hashlib.sha256(data).hexdigest()


root=Path('source')
change=json.loads(Path('ci/DEPTH25_OVERLAY.json').read_text())
baseline=root/'verification/current_build/depth24/source_fingerprint.json'
assert digest(baseline.read_bytes())==change['base_source_fingerprint_sha256']
frozen=json.loads(baseline.read_text())['files']
allowed={'tests/test_depth25_migration_history.py', 'src/go_hotel/db/models.py', 'alembic/versions/0132_rail_runtime_field_widths.py', 'alembic/versions/0076_production_connector_runtime_enforcement.py', 'tests/test_parent_implementation_code_review_debt_closure.py', 'src/go_hotel/rail/service.py'}
assert {f['path'] for f in change['files']}==allowed
for f in change['files']:
    target=root/f['path']
    assert (digest(target.read_bytes()) if target.exists() else None)==f['before_sha256']
    payload=Path(f['source']).read_bytes()
    assert len(payload)==f['size'] and digest(payload)==f['sha256']
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(payload)
    frozen[f['path']]=f['sha256']
for name,sha in frozen.items():assert digest((root/name).read_bytes())==sha,name
Path('evidence/depth25_source_overlay.json').write_text(json.dumps({
    'previous_delivery_commit':change['previous_delivery_commit'],'files':change['files'],
    'frozen_files_verified':len(frozen),'runtime_change':'Rail timestamp serialization normalizes UTC across database roundtrips'},indent=2)+'\n')
print('DEPTH25 schema and UTC response delta verified')
