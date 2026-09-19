"""Real shipped DRAFT registry rejects account creation; body changes need consent."""
import secrets
import pytest
from sqlalchemy import select,func
from go_hotel.db.models import IdentityUserRow
from test_hotel_direct_submission_full_app import full_application
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup
from registration_terms_test_support import approved_terms_fixture

@pytest.mark.parametrize('audience',['consumer','supplier'])
def test_shipped_unapproved_bodies_cannot_register(full_application,audience):
    client,data=full_application;factory=data[4]
    route='/v1/consumer/auth/registration' if audience=='consumer' else '/bff/auth/supplier/registration-terms'
    policy=client.get(route).json()['data']
    assert policy['enabled'] is False and policy['acceptance_enabled'] is False
    assert policy['documents']
    payload={'email':'blocked@example.test','password':secrets.token_urlsafe(24),'accepted_terms':True,
             'term_versions':policy.get('terms',policy['versions']),'term_hashes':policy['term_hashes']}
    if audience=='supplier':payload.update(organization_name='测试主体',contact_name='测试联系人')
    endpoint='/v1/consumer/auth/register' if audience=='consumer' else '/bff/auth/supplier/register'
    with factory() as session:before=session.scalar(select(func.count()).select_from(IdentityUserRow))
    response=client.post(endpoint,json=payload)
    assert response.status_code==503,response.text
    with factory() as session:assert session.scalar(select(func.count()).select_from(IdentityUserRow))==before

@pytest.mark.parametrize('audience',['consumer','supplier'])
def test_changed_body_hash_cannot_create_account(full_application,monkeypatch,audience):
    approved_terms_fixture(monkeypatch)
    client,data=full_application;factory=data[4]
    route='/v1/consumer/auth/registration' if audience=='consumer' else '/bff/auth/supplier/registration-terms'
    policy=client.get(route).json()['data']
    payload={'email':'changed@example.test','password':secrets.token_urlsafe(24),'accepted_terms':True,
             'term_versions':policy['versions'],'term_hashes':{k:'0'*64 for k in policy['term_hashes']}}
    if audience=='supplier':payload.update(organization_name='测试主体',contact_name='测试联系人')
    endpoint='/v1/consumer/auth/register' if audience=='consumer' else '/bff/auth/supplier/register'
    response=client.post(endpoint,json=payload)
    assert response.status_code==409 and 'CONTENT_MISMATCH' in response.json()['detail']


from test_registration_terms_registry import registry_copy, approve_fixture
from go_hotel.db.models import AuditEventRow

@pytest.mark.parametrize('audience',['consumer','supplier'])
def test_real_registry_synthetic_approved_text_binds_persisted_consent(full_application,registry_copy,audience):
    # Fictional test texts; shipped drafts are never approved by this test.
    approve_fixture(registry_copy)
    client,data=full_application;factory=data[4]
    route='/v1/consumer/auth/registration' if audience=='consumer' else '/bff/auth/supplier/registration-terms'
    policy=client.get(route).json()['data']
    assert policy['enabled'] and policy['acceptance_enabled']
    for doc in policy['documents']:
        response=client.get(doc['content_url'])
        assert response.status_code==200
        assert response.json()['data']['sha256']==policy['term_hashes'][doc['id']]
    payload={'email':'approved-fixture@example.test','password':secrets.token_urlsafe(24),'accepted_terms':True,
             'term_versions':policy['versions'],'term_hashes':policy['term_hashes']}
    if audience=='supplier':payload.update(organization_name='测试主体',contact_name='测试联系人')
    endpoint='/v1/consumer/auth/register' if audience=='consumer' else '/bff/auth/supplier/register'
    response=client.post(endpoint,json=payload)
    assert response.status_code in {200,201},response.text
    action='CONSUMER_REGISTRATION_TERMS_ACCEPTED' if audience=='consumer' else 'SUPPLIER_REGISTRATION_TERMS_ACCEPTED'
    with factory() as session:
        audit=session.scalar(select(AuditEventRow).where(AuditEventRow.action==action))
        assert audit.metadata_json['term_hashes']==policy['term_hashes']
        assert audit.metadata_json['term_versions']==policy['versions']
