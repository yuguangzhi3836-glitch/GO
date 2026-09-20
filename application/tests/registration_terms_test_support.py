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

def approved_terms_fixture(monkeypatch):
    # Synthetic fixture models an approved verification runtime only for local
    # identity-flow tests. It never approves the shipped legal drafts.
    from go_hotel.core.config import settings
    monkeypatch.setattr(settings, 'registration_verification_enabled', True)
    def policy(audience):
        versions=CONSUMER_REGISTRATION_TERMS if audience=='consumer' else SUPPLIER_REGISTRATION_TERMS
        digest=hashes(versions)
        return {'acceptance_enabled':True,'versions':dict(versions),'term_hashes':digest,
                'documents':[{'id':k,'title':k,'version':v,'sha256':digest[k],'status':'APPROVED',
                'content_url':'/v1/registration-terms/'+k+'/'+v} for k,v in versions.items()]}
    monkeypatch.setattr(terms,'registration_terms_status',policy)
    monkeypatch.setattr(terms,'require_registration_terms_ready',policy)
