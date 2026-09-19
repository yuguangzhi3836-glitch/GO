from copy import deepcopy
from hashlib import sha256
import json
import shutil
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from go_hotel.services import registration_terms as service
from go_hotel.api.routes.registration_terms import router

@pytest.fixture
def client():
    app = FastAPI(); app.include_router(router)
    return TestClient(app)

@pytest.fixture
def registry_copy(tmp_path, monkeypatch):
    shutil.copytree(service._REGISTRY_ROOT, tmp_path / 'terms')
    monkeypatch.setattr(service, '_REGISTRY_ROOT', tmp_path / 'terms')
    return service._REGISTRY_ROOT / service._DRAFT_VERSION / 'registry.json'

def approve_fixture(path):
    # Entirely synthetic texts + evidence in temporary directory, NOT approval of drafts.
    registry = json.loads(path.read_text())
    registry.update(release_status='APPROVED', unresolved=[])
    for key in service._REQUIRED_RELEASE_FIELDS: registry[key] = {'test_only': True}
    version = '2099-test-fixture-v1'
    folder = path.parent.parent / version; folder.mkdir()
    for item in registry['documents']:
        content = f"TEST ONLY fictional legal document: {item['id']}. Never use for registration."
        (folder / item['file']).write_text(content)
        digest = sha256(content.encode()).hexdigest()
        item.update(status='APPROVED', version=version, sha256=digest, effective_at='2026-01-01T00:00:00+00:00',
                    approval={'reviewer': 'TEST_ONLY', 'approved_at': '2026-01-01T00:00:00+00:00',
                              'evidence_ref': 'test-only', 'sha256': digest})
    path.write_text(json.dumps(registry)); return registry

@pytest.mark.parametrize('audience,count', [('consumer', 3), ('supplier', 5)])
def test_actual_drafts_readable_not_acceptable(client, audience, count):
    response = client.get('/v1/registration-terms', params={'audience': audience})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    data = response.json()['data']
    assert not data['acceptance_enabled'] and not data['enabled']
    assert len(data['documents']) == count
    for doc in data['documents']:
        body = client.get(doc['content_url']).json()['data']
        assert '待确认草稿' in body['content'] and len(body['content']) > 1400
        assert sha256(body['content'].encode()).hexdigest() == doc['sha256']
    with pytest.raises(ValueError, match='REGISTRATION_TERMS_NOT_READY'): service.require_registration_terms_ready(audience)

def test_exact_registered_version_only(client):
    assert client.get('/v1/registration-terms/privacy_policy/2026-08-25-v1').status_code == 404
    assert client.get('/v1/registration-terms/unknown/2026-09-19-draft-v1').status_code == 404
    assert client.get('/v1/registration-terms?audience=admin').status_code == 422
    assert client.post('/v1/registration-terms?audience=consumer', json={}).status_code == 405

def test_approved_synthetic_fixture(registry_copy):
    approve_fixture(registry_copy)
    status = service.require_registration_terms_ready('supplier')
    assert status['acceptance_enabled'] and len(status['term_hashes']) == 5

@pytest.mark.parametrize('change', ['missing_contact', 'missing_approval', 'wrong_hash', 'future', 'unresolved', 'future_approval', 'naive_approval', 'draft_banner'])
def test_partial_approval_cannot_open(registry_copy, change):
    registry = approve_fixture(registry_copy); item = registry['documents'][0]
    if change == 'missing_contact': registry['contact_channels'] = None
    elif change == 'missing_approval': item['approval'] = None
    elif change == 'wrong_hash': item['approval']['sha256'] = '0' * 64
    elif change == 'future': item['effective_at'] = '2999-01-01T00:00:00+00:00'
    elif change == 'future_approval': item['approval']['approved_at'] = '2999-01-01T00:00:00+00:00'
    elif change == 'naive_approval': item['approval']['approved_at'] = '2026-01-01T00:00:00'
    elif change == 'draft_banner':
        content = '待确认草稿｜版本 is not approved'
        (registry_copy.parent.parent / item['version'] / item['file']).write_text(content)
        item['sha256'] = item['approval']['sha256'] = sha256(content.encode()).hexdigest()
    else: registry['unresolved'] = ['STILL_UNCONFIRMED']
    registry_copy.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match='REGISTRATION_TERMS_NOT_READY'): service.require_registration_terms_ready('consumer')

def test_changed_text_fail_closed(client, registry_copy):
    registry = json.loads(registry_copy.read_text()); doc = registry['documents'][0]
    (registry_copy.parent / doc['file']).write_text('tampered body')
    assert client.get('/v1/registration-terms?audience=consumer').status_code == 503
    assert client.get(f"/v1/registration-terms/{doc['id']}/{doc['version']}").status_code == 503

def test_server_registry_path_cannot_escape(client, registry_copy):
    registry = json.loads(registry_copy.read_text()); registry['documents'][0]['file'] = '../../../../../etc/passwd'
    registry_copy.write_text(json.dumps(registry))
    assert client.get('/v1/registration-terms?audience=consumer').status_code == 503

def test_duplicate_identity_rejected(client, registry_copy):
    registry = json.loads(registry_copy.read_text()); registry['documents'].append(deepcopy(registry['documents'][0]))
    registry_copy.write_text(json.dumps(registry))
    assert client.get('/v1/registration-terms?audience=consumer').status_code == 503

def test_metadata_cannot_relabel_bundled_draft_as_formal(registry_copy):
    registry = json.loads(registry_copy.read_text())
    registry.update(release_status='APPROVED', unresolved=[])
    for key in service._REQUIRED_RELEASE_FIELDS: registry[key] = {'test_only': True}
    for item in registry['documents']:
        item.update(status='APPROVED', effective_at='2026-01-01T00:00:00+00:00',
                    approval={'sha256': item['sha256'], 'reviewer': 'TEST_ONLY',
                              'approved_at': '2026-01-01T00:00:00+00:00', 'evidence_ref': 'test-only'})
    registry_copy.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match='REGISTRATION_TERMS_NOT_READY'):
        service.require_registration_terms_ready('consumer')
