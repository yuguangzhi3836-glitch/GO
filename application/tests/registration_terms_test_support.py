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


def synthetic_mail_runtime(monkeypatch):
    """Synthetic mail transport only; durable challenge checks still run."""
    from go_hotel.core.config import settings
    from go_hotel.services import registration_email
    from go_hotel.services import registration_privacy
    monkeypatch.setattr(registration_privacy, 'operational_evidence_status', lambda: {'ready': True, 'digest': 'synthetic-only'})
    registration_privacy.cleanup_once()
    monkeypatch.setattr(settings, 'registration_verification_enabled', True)
    monkeypatch.setattr(registration_email, 'configuration', lambda: ({'test_only': True}, 'not-a-real-password'))


def with_verification(payload, audience):
    import pytest
    from go_hotel.services import registration_verification as verification, registration_email
    sent=[]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(registration_email, 'send_code', lambda email,code: sent.append(code))
        deferred=['personal_vault_terms'] if audience=='consumer' else ['data_processing_terms','electronic_signature_authorization']
        result=verification.issue(audience,payload['email'],'fixture-only',{'versions':payload['term_versions'],'term_hashes':payload['term_hashes'],'deferred':deferred,'account_stage':True})
    from go_hotel.services.registration_privacy import required_decisions
    deferred=['personal_vault_terms'] if audience=='consumer' else ['data_processing_terms','electronic_signature_authorization']
    return {**payload,'registration_decisions':required_decisions({'versions':payload['term_versions'],'deferred':deferred}),'challenge_id':result['challenge_id'],'verification_code':sent[-1]}
