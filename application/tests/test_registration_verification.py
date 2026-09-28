import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from sqlalchemy import select, event
from go_hotel.core.config import settings
from go_hotel.services import registration_verification as verify, registration_email as mail, registration_terms as terms
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RegistrationChallengeRow as Challenge, IdentityUserRow, ConsumerWalletRow, AuditEventRow
from registration_terms_test_support import approved_terms_fixture


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    original_configuration = mail.configuration
    approved_terms_fixture(monkeypatch)
    monkeypatch.setattr(mail,'configuration',original_configuration)
    monkeypatch.setattr(settings,'jwt_signing_key','isolated-registration-test-key-32bytes-only')
    secret=tmp_path/'existing-password';secret.write_text('isolated-only-password')
    cfg=tmp_path/'mail.json';cfg.write_text(json.dumps({'sender':mail.SENDER,'credential_reference':'hk-staging-registration-email','host':'smtp.test.invalid','port':465,'tls':'SSL','username':mail.SENDER,'password_file':str(secret)}))
    monkeypatch.setattr(settings,'registration_email_config_path',str(cfg))
    sent=[]
    monkeypatch.setattr(mail,'send_code',lambda address,code:sent.append((address,code)))
    return sent


def payload(client,audience,email):
    endpoint='/v1/consumer/auth/registration' if audience=='consumer' else '/bff/auth/supplier/registration-terms'
    p=client.get(endpoint).json()['data']
    from go_hotel.services.registration_privacy import required_decisions
    return dict(registration_decisions=required_decisions(p),email=email,password='Isolated-test-pass-123',accepted_terms=True,term_versions=p['versions'],term_hashes=p['term_hashes'])


def send(client,sent,audience='consumer',email='new@example.test'):
    body=payload(client,audience,email)
    r=client.post('/v1/registration/challenges',json={k:v for k,v in body.items() if k!='password'}|{'audience':audience})
    assert r.status_code==200,r.text
    assert 'code' not in r.json()['data']
    return body|{'challenge_id':r.json()['data']['challenge_id'],'verification_code':sent[-1][1]}


@pytest.mark.parametrize('audience',['consumer','supplier'])
def test_signup_requires_actual_code_and_audits_consumption(client,delivery,audience):
    b=send(client,delivery,audience)
    endpoint='/v1/consumer/auth/register' if audience=='consumer' else '/bff/auth/supplier/register'
    if audience=='supplier':b.update(organization_name='隔离测试企业',contact_name='测试联系人')
    assert client.post(endpoint,json=b|{'verification_code':'wrong'}).status_code==409
    result=client.post(endpoint,json=b)
    assert result.status_code in (200,201),result.text
    with SessionLocal() as s:
        row=s.scalar(select(Challenge));assert row.state=='CONSUMED' and row.consumed_by
        assert row.code_digest!=b['verification_code']
        audit=s.scalar(select(AuditEventRow).where(AuditEventRow.action==audience.upper()+'_REGISTRATION_TERMS_ACCEPTED'))
        assert audit.metadata_json['email_verified'] is True
        assert audit.metadata_json['verification_challenge_id']==b['challenge_id']
    assert client.post(endpoint,json=b).status_code==409


def test_boolean_flag_alone_never_enables_registration(client,monkeypatch):
    original_configuration = mail.configuration
    approved_terms_fixture(monkeypatch)
    monkeypatch.setattr(mail,'configuration',original_configuration)
    monkeypatch.setattr(settings,'registration_email_config_path','')
    assert client.get('/v1/consumer/auth/registration').json()['data']['enabled'] is False
    assert client.post('/v1/consumer/auth/register',json=payload(client,'consumer','no@example.test')).status_code==503


def test_missing_code_not_accepted(client,delivery):
    assert client.post('/v1/consumer/auth/register',json=payload(client,'consumer','no@example.test')).status_code==409


@pytest.mark.parametrize('mutation',['email','purpose','expired','policy','attempts'])
def test_proof_boundaries(client,delivery,monkeypatch,mutation):
    b=send(client,delivery)
    if mutation=='email': b['email']='other@example.test'
    elif mutation=='purpose':
        b.update(organization_name='测试企业',contact_name='联系人')
        assert client.post('/bff/auth/supplier/register',json=b|{'term_versions':terms.registration_terms_status('supplier')['versions'],'term_hashes':terms.registration_terms_status('supplier')['term_hashes']}).status_code==409
        return
    elif mutation=='expired':
        t=verify.now_ms();monkeypatch.setattr(verify,'now_ms',lambda:t+600_001)
    elif mutation=='policy':
        policy=terms.registration_terms_status('consumer');policy['term_hashes']={k:'a'*64 for k in policy['term_hashes']}
        monkeypatch.setattr(terms,'require_registration_terms_ready',lambda audience:policy)
        b['term_hashes']=policy['term_hashes']
    elif mutation=='attempts':
        wrong='000000' if b['verification_code']!='000000' else '111111'
        for _ in range(5):assert client.post('/v1/consumer/auth/register',json=b|{'verification_code':wrong}).status_code==409
    assert client.post('/v1/consumer/auth/register',json=b).status_code==409
    with SessionLocal() as s:assert s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==b['email'])) is None


def test_resend_replaces_old_code_and_limits_persist(client,delivery,monkeypatch):
    b=send(client,delivery)
    raw={k:v for k,v in b.items() if k in ('email','accepted_terms','term_versions','term_hashes','registration_decisions')}|{'audience':'consumer'}
    assert client.post('/v1/registration/challenges',json=raw).status_code==429
    t=verify.now_ms();monkeypatch.setattr(verify,'now_ms',lambda:t+60_001)
    newer=send(client,delivery)
    assert b['challenge_id']!=newer['challenge_id']
    assert client.post('/v1/consumer/auth/register',json=b).status_code==409
    assert client.post('/v1/consumer/auth/register',json=newer).status_code==200


def test_failed_delivery_not_usable_and_error_redacted(client,delivery,monkeypatch):
    def fail(*args):raise ValueError('REGISTRATION_EMAIL_SEND_FAILED')
    monkeypatch.setattr(mail,'send_code',fail)
    b=payload(client,'consumer','failure@example.test')
    r=client.post('/v1/registration/challenges',json={k:v for k,v in b.items() if k!='password'}|{'audience':'consumer'})
    assert r.status_code==503
    with SessionLocal() as s:assert s.scalar(select(Challenge)).state=='FAILED'


def test_wallet_failure_rolls_back_code_and_account(client,delivery):
    b=send(client,delivery)
    def fail(*args):raise RuntimeError('wallet failure')
    event.listen(ConsumerWalletRow,'before_insert',fail)
    try:
        with pytest.raises(RuntimeError):client.post('/v1/consumer/auth/register',json=b)
    finally:event.remove(ConsumerWalletRow,'before_insert',fail)
    with SessionLocal() as s:
        assert s.scalar(select(Challenge)).state=='SENT'
        assert s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==b['email'])) is None
    assert client.post('/v1/consumer/auth/register',json=b).status_code==200


def test_concurrent_consume_exactly_once(client,delivery):
    b=send(client,delivery)
    proof=verify.check('consumer',b['email'],b['challenge_id'],b['verification_code'],terms.registration_terms_status('consumer'))
    def consume(n):
        try:
            with SessionLocal.begin() as s:verify.consume(s,proof,'isolated-user-'+str(n))
            return 'ok'
        except ValueError:return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(consume,[1,2]))
    assert sorted(results)==['ok','refused']


def test_no_email_until_terms_and_consent_ready(client,delivery,monkeypatch):
    b=payload(client,'consumer','nobody@example.test')
    args={k:v for k,v in b.items() if k!='password'}|{'audience':'consumer'}
    assert client.post('/v1/registration/challenges',json=args|{'accepted_terms':False}).status_code==422
    assert not delivery
    monkeypatch.setattr(terms,'_unused',None,raising=False)
    import go_hotel.api.routes.registration_verification as routes
    def blocked(audience):raise ValueError('REGISTRATION_TERMS_NOT_READY')
    monkeypatch.setattr(routes,'require_registration_terms_ready',blocked)
    assert client.post('/v1/registration/challenges',json=args).status_code==503
    assert not delivery


def test_smtp_uses_existing_secret_tls_and_fixed_sender(tmp_path,monkeypatch):
    secret=tmp_path/'mounted';secret.write_text('fake-password')
    cfg=tmp_path/'config';cfg.write_text(json.dumps(dict(sender=mail.SENDER,credential_reference='hk-staging-registration-email',host='smtp.test.invalid',port=587,tls='STARTTLS',username=mail.SENDER,password_file=str(secret))))
    monkeypatch.setattr(settings,'registration_email_config_path',str(cfg))
    calls=[]
    class SMTP:
        def __init__(self,*args,**kwargs):calls.append('connect')
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def ehlo(self):calls.append('ehlo')
        def starttls(self,**kwargs):calls.append('tls')
        def login(self,*args):calls.append('login');assert args==(mail.SENDER,'fake-password')
        def send_message(self,msg,**kwargs):calls.append('send');assert kwargs['from_addr']==mail.SENDER;return {}
    monkeypatch.setattr(mail.smtplib,'SMTP',SMTP)
    mail.send_code('recipient@example.test','123456')
    assert calls==['connect','ehlo','tls','ehlo','login','send']
    def leak(*args,**kwargs):raise OSError('fake-password 123456 recipient@example.test')
    monkeypatch.setattr(mail.smtplib,'SMTP',leak)
    with pytest.raises(ValueError,match='^REGISTRATION_EMAIL_SEND_FAILED$'):mail.send_code('recipient@example.test','123456')


def test_transport_peer_limit_shared_between_audiences(client,delivery):
    for n in range(20):
        send(client,delivery,'consumer' if n%2 else 'supplier',f'user{n}@example.test')
    b=payload(client,'consumer','last@example.test')
    r=client.post('/v1/registration/challenges',json={k:v for k,v in b.items() if k!='password'}|{'audience':'consumer'})
    assert r.status_code==429 and len(delivery)==20


def test_concurrent_send_one_message(client,delivery):
    policy=terms.registration_terms_status('consumer')
    def issue(n):
        try:verify.issue('consumer','concurrent@example.test','isolated-peer',policy);return 'sent'
        except ValueError as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(issue,[1,2]))
    assert sorted(results)==['REGISTRATION_CODE_RATE_LIMITED','sent']
    assert len(delivery)==1
