"""Scoped API integration with real password, JWT and database sessions.

Isolated synthetic accounts and SQLite; not a full-app or browser acceptance.
"""
import secrets
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from go_hotel.security import service as identitymod
from go_hotel.security.mfa import totp
from go_hotel.api.routes import hotel_direct_submission as routes
from go_hotel.services import hotel_partner_core as coremod
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup


@pytest.fixture
def real_identity(publishing, monkeypatch):
    pub, review, pid, manifest, factory, verifier, row = publishing
    monkeypatch.setattr(identitymod, 'SessionLocal', factory)
    monkeypatch.setattr(routes, 'reviews', review)
    monkeypatch.setattr(routes, 'publication', pub)
    app = FastAPI()
    app.include_router(routes.router)
    identity = identitymod.identity_service

    def login(username, actor, supplier, roles):
        password = secrets.token_urlsafe(32)
        identity.ensure_user(username, password, actor, supplier, roles)
        with pytest.raises(ValueError, match='INVALID_CREDENTIALS'):
            identity.login(username, 'incorrect-password', expected_actor_type=actor)
        if actor == 'GO_ADMIN':
            enrollment = identity.begin_admin_mfa_enrollment(username, password)
            identity.confirm_admin_mfa_enrollment(enrollment['enrollment_token'], totp(enrollment['secret']))
            tokens = identity.login(username, password, totp_code=totp(enrollment['secret']), expected_actor_type=actor)
        else:
            tokens = identity.login(username, password, expected_actor_type=actor)
        return {'Authorization': 'Bearer ' + tokens['access_token']}

    with TestClient(app) as client:
        yield client, login, publishing, identity


def test_password_session_roles_and_revocation(real_identity):
    client, login, data, identity = real_identity
    row = data[-1]
    url = '/internal/v1/hotel-autopage/direct-submission-reviews/' + row['review_id']
    assert client.get(url).status_code == 401
    supplier = login('supplier', 'SUPPLIER_USER', 'one', ['SUPPLIER_OWNER'])
    assert client.get(url, headers=supplier).status_code == 403
    observer = login('observer', 'GO_ADMIN', None, ['GO_READ_ONLY'])
    assert client.get(url, headers=observer).status_code == 403
    admin = login('admin', 'GO_ADMIN', None, ['GO_RULE_ADMIN'])
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(url, headers=admin | {'X-GO-Actor':'SUPPLIER_USER'}).status_code == 403
    principal = identity.authenticate(admin['Authorization'].removeprefix('Bearer '))
    identity.revoke_session(principal.session_id)
    assert client.get(url, headers=admin).status_code == 401


def test_real_supplier_session_cannot_submit_another_hotel(real_identity):
    client, login, data, identity = real_identity
    pub, review, pid, manifest, factory, verifier, row = data
    owner = login('owner', 'SUPPLIER_USER', 'one', ['SUPPLIER_OWNER'])
    other = login('other', 'SUPPLIER_USER', 'two', ['SUPPLIER_OWNER'])
    other_pid = coremod.hotel_partner_core_service.create_property('two', 'other', {'name_zh':'Second test hotel','property_type':'HOTEL'})['property_id']
    url = f'/v1/supplier/properties/{pid}/direct-submission-reviews'
    assert client.post(url, headers=other, json={'manifest':manifest}).status_code == 409
    wrong_property = f'/v1/supplier/properties/{other_pid}/direct-submission-reviews'
    assert client.post(wrong_property, headers=owner, json={'manifest':manifest}).status_code == 409
    assert client.post(url, headers=owner, json={'manifest':manifest}).status_code == 201


def test_real_admin_session_publishes_and_revokes_original(real_identity):
    client, login, data, identity = real_identity
    pub, review, pid, manifest, factory, verifier, row = data
    admin = login('publisher', 'GO_ADMIN', None, ['GO_RULE_ADMIN'])
    prefix = '/internal/v1/hotel-autopage/direct-submission-reviews/' + row['review_id']
    original = '/v1/hotel-pages/direct-submissions/' + row['review_id'] + '/media/' + manifest['assets'][0]['asset_id']
    assert client.get(original).status_code == 404
    assert client.post(prefix+'/publish', headers=admin).status_code == 200
    assert client.get(original).status_code == 200
    assert client.post(prefix+'/publish', headers=admin).json()['data']['idempotent'] is True
    assert client.post(prefix+'/revoke', headers=admin).status_code == 200
    assert client.get(original).status_code == 404
