"""Real router/services with synthetic principals, not production login tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from go_hotel.security.deps import current_principal
from go_hotel.security.service import Principal
from go_hotel.api.routes import hotel_direct_submission as routes
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup

@pytest.fixture
def api(publishing, monkeypatch):
    pub, review, pid, manifest, factory, verifier, row = publishing
    monkeypatch.setattr(routes, 'reviews', review)
    monkeypatch.setattr(routes, 'publication', pub)
    app = FastAPI(); app.include_router(routes.router)
    def login(actor='GO_ADMIN', permissions=None, supplier=None):
        app.dependency_overrides[current_principal] = lambda: Principal(
            'test-user','test',actor,supplier,[],'synthetic-session',
            {'admin:rules'} if permissions is None else permissions)
    with TestClient(app) as client:
        yield client, login, publishing

@pytest.mark.parametrize('operation',['','/approve','/revoke','/publish'])
def test_administrator_permissions_cannot_be_bypassed(api, operation):
    client, login, data = api
    row = data[-1]; url='/internal/v1/hotel-autopage/direct-submission-reviews/'+row['review_id']+operation
    def request():
        return client.get(url) if not operation else client.post(url,json={'expected_sha256':row['manifest_sha256']})
    assert request().status_code == 401
    login('SUPPLIER_USER', supplier='one')
    assert request().status_code == 403
    login(permissions=set())
    assert request().status_code == 403

def test_submit_exact_hash_publish_original_and_revoke(api):
    client, login, data=api
    pub, review, pid, manifest, factory, verifier, old=data
    login('SUPPLIER_USER',supplier='other')
    path=f'/v1/supplier/properties/{pid}/direct-submission-reviews'
    assert client.post(path,json={'manifest':manifest}).status_code==409
    login('SUPPLIER_USER',supplier='one')
    response=client.post(path,json={'manifest':manifest}); assert response.status_code==201
    row=response.json()['data']; prefix='/internal/v1/hotel-autopage/direct-submission-reviews/'+row['review_id']
    login()
    facts_hash=client.get(prefix+'/inspection').json()['data']['facts_sha256']
    assert client.post(prefix+'/approve',json={'expected_sha256':'0'*64,'expected_facts_sha256':facts_hash}).status_code==409
    assert client.get(prefix).json()['data']['state']=='SUBMITTED'
    assert client.post(prefix+'/approve',json={'expected_sha256':row['manifest_sha256'],'expected_facts_sha256':facts_hash}).status_code==200
    url='/v1/hotel-pages/direct-submissions/'+row['review_id']+'/media/'+manifest['assets'][0]['asset_id']
    assert client.get(url).status_code==404
    response=client.post(prefix+'/publish'); assert response.status_code==200, response.text
    assert response.json()['data']['published'] is True
    image=client.get(url); assert image.status_code==200 and image.content.startswith(b'\xff\xd8')
    assert image.headers['cache-control']=='no-store'
    assert client.post(prefix+'/publish').json()['data']['idempotent'] is True
    assert client.post(prefix+'/revoke').status_code==200
    assert client.get(url).status_code==404
    assert client.post(prefix+'/publish').status_code==409
