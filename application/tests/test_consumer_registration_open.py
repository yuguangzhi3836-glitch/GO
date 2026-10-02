"""Real persisted consumer signup, without session/principal overrides."""
import pytest
from registration_terms_test_support import approved_terms_fixture, hashes, with_verification
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from go_hotel.db.models import Base, IdentityUserRow, ConsumerProfileRow, ConsumerWalletRow, AuditEventRow
from go_hotel.consumer import service as consumer
from go_hotel.security import service as identity
from go_hotel.api.routes import consumer_identity as routes

@pytest.fixture
def signup(tmp_path, monkeypatch):
    approved_terms_fixture(monkeypatch)
    engine=create_engine('sqlite:///'+str(tmp_path/'signup.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    from go_hotel.services import registration_verification
    for module in (consumer, identity, routes, registration_verification):monkeypatch.setattr(module,'SessionLocal',factory)
    app=FastAPI();app.include_router(routes.router)
    with TestClient(app) as client:yield client,factory
    engine.dispose()

def body():return dict(email='traveler@example.test',password='Long-test-pass-123',accepted_terms=True,term_versions=routes.CONSUMER_REGISTRATION_TERMS,term_hashes=hashes(routes.CONSUMER_REGISTRATION_TERMS))

def test_national_registration_real_identity_cookie_and_audit(signup):
    client,factory=signup
    options=client.get('/v1/consumer/auth/registration').json()['data']
    assert options['coverage']=='CN_NATIONWIDE' and options['enabled']
    payload=with_verification(body(),'consumer');payload['email']=' Traveler@Example.Test '
    response=client.post('/v1/consumer/auth/register',json=payload)
    assert response.status_code==200,response.text
    assert 'HttpOnly' in response.headers['set-cookie']
    assert response.json()['data']['profile']['email']=='traveler@example.test'
    with factory() as s:
        user=s.scalar(select(IdentityUserRow))
        assert user.actor_type=='CONSUMER' and user.roles==['CONSUMER'] and user.supplier_id is None
        assert s.scalar(select(ConsumerProfileRow)).user_id==user.user_id
        assert s.scalar(select(ConsumerWalletRow)).user_id==user.user_id
        audit=s.scalar(select(AuditEventRow).where(AuditEventRow.action=='CONSUMER_REGISTRATION_TERMS_ACCEPTED'))
        assert audit.metadata_json['term_versions']==routes.CONSUMER_REGISTRATION_TERMS
        assert audit.metadata_json['personal_vault_opt_in'] is False
    assert client.post('/v1/consumer/auth/register',json=payload).status_code==409

@pytest.mark.parametrize('change,remove,status',[
    ({},'accepted_terms',422),({},'term_versions',422),({'accepted_terms':False},None,422),
    ({'accepted_terms':'true'},None,422),({'term_versions':{}},None,409),
    ({'email':'bad-email'},None,422),({'password':'short'},None,422),
    ({'roles':['GO_GOVERNANCE']},None,422),({'actor_type':'GO_ADMIN'},None,422),
    ({'supplier_id':'foreign'},None,422),
])
def test_invalid_signup_has_no_account_side_effect(signup,change,remove,status):
    client,factory=signup;payload=body()|change
    if remove:payload.pop(remove)
    assert client.post('/v1/consumer/auth/register',json=payload).status_code==status
    with factory() as s:
        assert s.scalar(select(IdentityUserRow)) is None
        assert s.scalar(select(ConsumerProfileRow)) is None

def test_wallet_failure_rolls_back_identity_profile_and_consent(signup):
    from sqlalchemy import event
    client,factory=signup
    def fail_wallet(mapper, connection, target):raise RuntimeError('simulated wallet storage failure')
    payload=with_verification(body(),'consumer')
    event.listen(ConsumerWalletRow,'before_insert',fail_wallet)
    try:
        with pytest.raises(RuntimeError,match='simulated wallet'):
            client.post('/v1/consumer/auth/register',json=payload)
    finally:event.remove(ConsumerWalletRow,'before_insert',fail_wallet)
    with factory() as s:
        assert s.scalar(select(IdentityUserRow)) is None
        assert s.scalar(select(ConsumerProfileRow)) is None
        assert s.scalar(select(ConsumerWalletRow)) is None
        assert s.scalar(select(AuditEventRow)) is None
    assert client.post('/v1/consumer/auth/register',json=payload).status_code==200
