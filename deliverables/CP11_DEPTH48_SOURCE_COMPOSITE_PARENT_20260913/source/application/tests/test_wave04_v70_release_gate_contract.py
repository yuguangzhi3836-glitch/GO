import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(name): return json.loads((ROOT/name).read_text(encoding='utf-8'))

def test_current_source_identity_does_not_inherit_historical_authority():
    t=(ROOT/'CURRENT_CONTROL_VERSION.md').read_text(encoding='utf-8')
    assert 'GO_CANONICAL_PARENT_RETENTION_20260912' in t
    assert 'Application source: application/' in t
    assert 'ACCEPTANCE_PENDING / NOT_DEPLOYED' in t
    assert 'It grants no operational, organizational, legal, signing, merge, migration, or deployment authority.' in t
    assert 'Historical content SHA256: 3e4ca4f958746d81214e896e240c910d5e1e62d53e3e4f667083935eea03e097' in t
    assert 'Unique controlling solution master:' not in t
    assert 'HK-STAGING runtime is separately archived' in t

def test_source_candidate_head_is_0114_and_not_staging_fact():
    d=load('CURRENT_RELEASE_MANIFEST.json'); m=d['migration']
    assert m['source_candidate']['revision_count']==114
    assert m['source_candidate']['single_head']=='0114_ext_truth_incident_hard'
    assert m['source_candidate']['down_revision']=='0113_ext_truth_ops_20260901'
    assert m['hong_kong_staging_confirmed']['current_head']=='0111_test_account_expiry'
    assert m['deployment_preflight_policy']['do_not_claim_0114_applied_before_staging_execution'] is True

def test_release_candidate_manifest_has_same_migration_truth_split():
    d=load('RELEASE_CANDIDATE_MANIFEST.json'); m=d['migration']
    assert m['source_candidate']['revision_count']==114
    assert m['source_candidate']['down_revision']=='0113_ext_truth_ops_20260901'
    assert m['hong_kong_staging_confirmed']['row_count']==1
    assert m['deployment_preflight_policy']['stamp_allowed'] is False

def test_wave07_frg02_release_identity_binds_wave07_parent_sha():
    d=load('CURRENT_RELEASE_MANIFEST.json')['wave07_frg02_release_control']
    assert d['release_id']=='GO-V7.0-PARALLEL-WAVE07-FRG02-20260831'
    assert d['parent_release_id']=='GO-V7.0-PARALLEL-WAVE07-20260831'
    assert d['immutable_parent_zip_sha256']=='638d27279c6d06063a4ae9a725a7c2a172b9874e183239388faf01a061efee70'

def test_wave07_frg02_binding_is_not_deployed_and_has_source_sha():
    d=load('WAVE07_FRG02_RELEASE_BINDING_20260831.json')
    assert d['deployment_status']=='NOT_DEPLOYED'
    assert len(d['source_tree_sha256'])==64
    int(d['source_tree_sha256'],16)

def test_v70_gate_is_authoritative_and_present():
    d=load('CURRENT_RELEASE_MANIFEST.json')['wave07_frg02_release_control']
    assert d['full_release_gate']=='scripts/release_gate_v70.sh'
    assert (ROOT/d['full_release_gate']).is_file()


def test_0113_0114_migration_bytes_are_audit_frozen():
    import hashlib
    expected = {
        'alembic/versions/0113_ext_truth_ops_20260901.py': 'dff0c7b45796c7476062b890b0711ced607c6d3f88215f35653279c267e2cc6b',
        'alembic/versions/0114_ext_truth_incident_hard.py': '25a9ea1e25f5a4bf600928621413d042f19513d07b3c4313df31b7a846c95a59',
    }
    for rel, digest in expected.items():
        assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() == digest
