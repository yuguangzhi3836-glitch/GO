"""Actual main app, lifespan, BFF cookies and security middleware; isolated data.

Does not launch a browser or establish staging/production readiness.
"""
import re
import secrets
import sys
from urllib.parse import urljoin
import pytest
from fastapi.testclient import TestClient
from go_hotel.core.config import settings
from go_hotel.security.service import identity_service
from go_hotel.security.mfa import totp
from go_hotel.api.routes import hotel_direct_submission as routes
from go_hotel.services.hotel_partner_core import hotel_partner_core_service
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup


@pytest.fixture
def full_application(publishing, monkeypatch):
    # Disable worker/egress settings before entering the real lifespan.
    for key in ('hosted_reservation_expiry_worker_enabled','vertical_reservation_expiry_worker_enabled','model_gateway_external_egress_enabled','travel_intelligence_enabled','oidc_enabled'):
        monkeypatch.setattr(settings,key,False)
    monkeypatch.setattr(settings,'app_env','test')
    monkeypatch.setattr(settings,'mfa_required_for_admin',True)
    for key in ('bootstrap_admin_username','bootstrap_admin_password','bootstrap_supplier_username','bootstrap_supplier_password'):
        monkeypatch.setattr(settings,key,'isolated-'+secrets.token_hex(16))
    from go_hotel.main import app
    pub, review, pid, manifest, factory, verifier, row = publishing
    # Every imported service/route uses this one fixture-owned SQLite database.
    for name, module in list(sys.modules.items()):
        if name.startswith('go_hotel.') and module is not None and 'SessionLocal' in vars(module):
            monkeypatch.setattr(module,'SessionLocal',factory)
    monkeypatch.setattr(routes,'reviews',review)
    monkeypatch.setattr(routes,'publication',pub)
    assert not app.dependency_overrides
    with TestClient(app,base_url='https://testserver') as client:
        yield client,publishing


def supplier_login(client, name, sid):
    client.cookies.clear()
    password=secrets.token_urlsafe(32)
    identity_service.create_user(name,password,'SUPPLIER_USER',sid,['SUPPLIER_OWNER'])
    response=client.post('/bff/auth/login',json={'username':name,'password':password,'expected_actor_type':'SUPPLIER_USER'})
    assert response.status_code==200,response.text
    assert client.get('/bff/auth/me').json()['data']['supplier_id']==sid
    return {'X-GO-Actor':'SUPPLIER_USER',settings.csrf_header_name:client.cookies.get(settings.csrf_cookie_name)}


def test_full_app_cookie_mfa_csrf_review_and_publication(full_application):
    client,data=full_application
    pub,review,pid,manifest,factory,verifier,old=data
    assert client.get('/health').status_code==200
    owner=supplier_login(client,'owner','one')
    path=f'/v1/supplier/properties/{pid}/direct-submission-reviews'
    response=client.post(path,headers=owner,json={'manifest':manifest})
    assert response.status_code==201,response.text
    row=response.json()['data']; prefix='/internal/v1/hotel-autopage/direct-submission-reviews/'+row['review_id']
    assert client.get(prefix,headers=owner).status_code==403
    client.cookies.clear()
    password=secrets.token_urlsafe(32)
    identity_service.create_user('review-admin',password,'GO_ADMIN',None,['GO_RULE_ADMIN'])
    denied=client.post('/bff/auth/login',json={'username':'review-admin','password':password,'expected_actor_type':'GO_ADMIN'})
    assert denied.status_code==401 and denied.json()['detail']=='MFA_ENROLLMENT_REQUIRED'
    enrollment=client.post('/bff/auth/mfa/enroll/start',json={'username':'review-admin','password':password}).json()['data']
    enrolled=client.post('/bff/auth/mfa/enroll/confirm',json={'enrollment_token':enrollment['enrollment_token'],'code':totp(enrollment['secret'])})
    assert enrolled.status_code==200,enrolled.text
    csrf=client.cookies.get(settings.csrf_cookie_name)
    admin={'X-GO-Actor':'GO_ADMIN',settings.csrf_header_name:csrf}
    inspected=client.get(prefix+'/inspection',headers=admin)
    assert inspected.status_code==200,inspected.text
    inspection=inspected.json()['data']
    body={'expected_sha256':row['manifest_sha256'],'expected_facts_sha256':inspection['facts_sha256']}
    assert client.post(prefix+'/approve',json=body).status_code==403
    assert client.post(prefix+'/approve',headers=admin|{settings.csrf_header_name:'wrong'},json=body).status_code==403
    approved=client.post(prefix+'/approve',headers=admin,json=body)
    assert approved.status_code==200,approved.text
    published=client.post(prefix+'/publish',headers=admin)
    assert published.status_code==200,published.text
    original='/v1/hotel-pages/direct-submissions/'+row['review_id']+'/media/'+manifest['assets'][0]['asset_id']
    assert client.get(original).status_code==200
    assert client.post(prefix+'/publish',headers=admin).json()['data']['idempotent'] is True
    assert client.post(prefix+'/revoke',headers=admin).status_code==200
    assert client.get(original).status_code==404
    assert client.post('/bff/auth/logout',headers=admin).status_code==200
    assert client.get(prefix).status_code==401


def test_full_app_hotel_switch_isolation_and_static_entry_assets(full_application):
    client,data=full_application
    pid=data[2]
    second=hotel_partner_core_service.create_property('one','owner',{'name_zh':'Second owned hotel','property_type':'HOTEL'})['property_id']
    foreign=hotel_partner_core_service.create_property('two','foreign',{'name_zh':'Foreign hotel','property_type':'HOTEL'})['property_id']
    owner=supplier_login(client,'switch-owner','one')
    for property_id in (pid,second,pid):
        response=client.get(f'/v1/supplier/properties/{property_id}/product-graph',headers=owner)
        assert response.status_code==200,response.text
        assert response.json()['data']['property']['property_id']==property_id
    assert client.get(f'/v1/supplier/properties/{foreign}/product-graph',headers=owner).status_code in {403,404}
    checked=set()
    for entry in ('/go-admin/','/supplier-console/','/go-app/'):
        page=client.get(entry)
        assert page.status_code==200 and 'text/html' in page.headers['content-type']
        for target in re.findall(r'(?:src|href)=["\']([^"\']+)',page.text):
            if not re.search(r'\.(?:js|css)(?:\?|$)',target):continue
            target=urljoin(entry,target)
            assert client.get(target).status_code==200,target
            checked.add(target)
    print('FULL_APP_STATIC_ASSETS_OK='+str(len(checked)))
