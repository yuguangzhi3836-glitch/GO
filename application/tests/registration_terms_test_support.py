"""Synthetic APPROVED policy for identity-flow tests only, never production authority.

The actual body/approval registry is tested independently. No authentication,
actor, cookie, CSRF, database transaction, or permission dependency is mocked.
"""
import hashlib
from go_hotel.services import registration_terms as terms
from go_hotel.api.routes.consumer_identity import CONSUMER_REGISTRATION_TERMS
from go_hotel.api.routes.bff import SUPPLIER_REGISTRATION_TERMS

def hashes(versions):
    return {k:hashlib.sha256(('SYNTHETIC TEST BODY '+k).encode()).hexdigest() for k in versions}

def account_versions(audience):
    source=CONSUMER_REGISTRATION_TERMS if audience=='consumer' else SUPPLIER_REGISTRATION_TERMS
    ids=('consumer_service_terms','privacy_policy') if audience=='consumer' else (
        'supplier_service_terms','privacy_policy','platform_operating_rules')
    return {k:source[k] for k in ids}

def approved_terms_fixture(monkeypatch):
    # Synthetic fixture models an approved verification runtime only for local
    # identity-flow tests. It never approves the shipped legal drafts.
    from go_hotel.core.config import settings
    synthetic_mail_runtime(monkeypatch)
    def policy(audience):
        versions=account_versions(audience)
        digest=hashes(versions)
        deferred=['personal_vault_terms'] if audience=='consumer' else ['data_processing_terms','electronic_signature_authorization']
        return {'acceptance_enabled':True,'enabled':True,'account_stage':True,'formal_approval_pending':False,
                'versions':dict(versions),'term_hashes':digest,'deferred':deferred,
                'documents':[{'id':k,'title':k,'version':v,'sha256':digest[k],'status':'APPROVED',
                'content_url':'/v1/registration-terms/'+k+'/'+v} for k,v in versions.items()]}
    monkeypatch.setattr(terms,'registration_terms_status',policy)
    monkeypatch.setattr(terms,'require_registration_terms_ready',policy)
    monkeypatch.setattr(terms,'account_registration_terms_status',policy)
    monkeypatch.setattr(terms,'require_account_registration_terms_ready',policy)


def register_synthetic_consumer(client, *, json):
    """Use accepted synthetic terms for legacy journey account fixtures only.

    Only this request sees the test policy. Real auth, cookies, persistence and
    admission validation run normally; the shipped policy is restored on exit.
    """
    import pytest
    with pytest.MonkeyPatch.context() as patch:
        approved_terms_fixture(patch)
        versions=account_versions('consumer')
        payload = {**json, 'accepted_terms': True,
                   'term_versions': versions,
                   'term_hashes': hashes(versions)}
        payload = with_verification(payload, 'consumer')
        return client.post('/v1/consumer/auth/register', json=payload)


def deferred_for(audience):
    return ['personal_vault_terms'] if audience=='consumer' else ['data_processing_terms','electronic_signature_authorization']


def synthetic_mail_runtime(monkeypatch):
    """Synthetic mail + SMS transports only; durable challenge checks still run."""
    from go_hotel.core.config import settings
    from go_hotel.services import registration_email, registration_sms, registration_privacy
    monkeypatch.setattr(registration_privacy, 'operational_evidence_status', lambda: {'ready': True, 'digest': 'synthetic-only'})
    registration_privacy.cleanup_once()
    monkeypatch.setattr(settings, 'registration_verification_enabled', True)
    # A modelled runtime has to be able to digest, or `ready()` is False and every
    # challenge call refuses before it reaches the durable checks this fixture
    # exists to exercise. The shipped default key is a `dev-` placeholder and is
    # deliberately unusable, so the fixture supplies its own — the *same* bytes the
    # session-scoped fixture in `conftest.py` installs. That matters: this fixture
    # is also used through `MonkeyPatch.context()`, which reverts on exit, and a
    # token minted inside such a context would fail to verify outside it with
    # `INVALID_SIGNATURE` if the value differed. Every caller of
    # `register_synthetic_consumer` relies on that equality, so the key is taken
    # from the shared constant rather than restated here.
    from conftest import SYNTHETIC_SIGNING_KEY
    monkeypatch.setattr(settings, 'jwt_signing_key', SYNTHETIC_SIGNING_KEY)
    monkeypatch.setattr(registration_email, 'configuration', lambda: ({'test_only': True}, 'not-a-real-password'))


def supplier_identifiers(payload):
    """Fill the two identifiers the supplier door collects, if a test omitted them.

    Derived from the address so every payload keeps its own account, and shaped to
    satisfy the real validators rather than sneaking past them.
    """
    import hashlib
    import re
    email = str(payload.get('email') or 'supplier@example.test').strip().lower()
    local = re.sub(r'[^a-z0-9_.-]', '', email.split('@')[0].lower())
    local = re.sub(r'^[^a-z0-9]+', '', local)[:24] or 'supplier'
    digits = ''.join(str(int(c, 16) % 10) for c in hashlib.sha256(email.encode()).hexdigest())[:9]
    return {'username': payload.get('username') or local, 'phone': payload.get('phone') or '13' + digits}


def with_verification(payload, audience):
    """Attach proved challenges for every identifier this audience has to prove.

    Consumer sign-up proves one address (email). Supplier sign-up proves two —
    email *and* mobile — so the payload carries two independent proofs; the account
    is created only once both are accepted.
    """
    import pytest
    from go_hotel.services import registration_verification as verification, registration_email, registration_sms
    from go_hotel.services.registration_privacy import required_decisions
    deferred = deferred_for(audience)
    policy = {'versions': payload['term_versions'], 'term_hashes': payload['term_hashes'], 'deferred': deferred, 'account_stage': True}
    sent = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(registration_email, 'send_code', lambda address, code: sent.append(('email', address, code)))
        # `verification.ready()` consults the email transport (or the operator's
        # test code); SMS delivery is stubbed here exactly as the service calls it.
        patch.setattr(registration_sms, 'send_code', lambda address, code: sent.append(('sms', address, code)))
        if audience == 'supplier':
            payload = {**payload, **supplier_identifiers(payload)}
            email_result = verification.issue(audience, payload['email'], 'fixture-only', policy, 'email')
            sms_result = verification.issue(audience, payload['phone'], 'fixture-only', policy, 'sms')
        else:
            result = verification.issue(audience, payload['email'], 'fixture-only', policy)
    body = {**payload, 'registration_decisions': required_decisions({'versions': payload['term_versions'], 'deferred': deferred})}
    if audience == 'supplier':
        codes = {channel: code for channel, _, code in sent}
        return {**body, 'email_challenge_id': email_result['challenge_id'], 'email_verification_code': codes['email'],
                'sms_challenge_id': sms_result['challenge_id'], 'sms_verification_code': codes['sms']}
    return {**body, 'challenge_id': result['challenge_id'], 'verification_code': sent[-1][2]}
