"""Versioned, hash-bound registration documents; bundled drafts never enable signup."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from go_hotel.core.config import settings
from pathlib import Path

_REGISTRY_ROOT = Path(__file__).resolve().parents[1] / 'legal' / 'registration'
_DRAFT_VERSION = '2026-09-19-draft-v2'
_REQUIRED = {
    'consumer': ('consumer_service_terms', 'privacy_policy', 'personal_vault_terms'),
    'supplier': ('supplier_service_terms', 'privacy_policy', 'data_processing_terms',
                 'electronic_signature_authorization', 'platform_operating_rules'),
}
_ACCOUNT_REQUIRED = {
    'consumer': ('consumer_service_terms', 'privacy_policy'),
    'supplier': ('supplier_service_terms', 'privacy_policy', 'platform_operating_rules'),
}
_ACCOUNT_DEFERRED = {
    'consumer': ('personal_vault_terms',),
    'supplier': ('data_processing_terms', 'electronic_signature_authorization'),
}
_REQUIRED_RELEASE_FIELDS = ('operator', 'contact_channels', 'retention_schedule',
                            'recipients', 'cross_border_assessment')


def _load_registry() -> dict:
    version = settings.registration_terms_version
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}', version):
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    return json.loads((_REGISTRY_ROOT / version / 'registry.json').read_text(encoding='utf-8'))


def _document(registry: dict, term_id: str, version: str) -> dict:
    # Resolve ONLY a server-registered id/version; no client-supplied filesystem path.
    entries = [x for x in registry['documents'] if x['id'] == term_id and x['version'] == version]
    if len(entries) != 1:
        raise ValueError('REGISTRATION_TERMS_NOT_FOUND')
    item = entries[0]
    root = _REGISTRY_ROOT.resolve()
    path = (root / item['version'] / item['file']).resolve()
    if root not in path.parents or path.suffix != '.md':
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    try:
        raw = path.read_bytes()
        content = raw.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR') from exc
    digest = sha256(raw).hexdigest()
    if digest != item['sha256'] or not content.strip():
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    return {key: item[key] for key in ('id', 'title', 'version', 'status')} | {
        'sha256': digest, 'content_url': f"/v1/registration-terms/{term_id}/{version}",
        'content': content, 'content_type': 'text/markdown; charset=utf-8',
        'effective_at': item.get('effective_at'),
    }


def read_registration_term(term_id: str, version: str) -> dict:
    return _document(_load_registry(), term_id, version)


def registration_terms_status(audience: str) -> dict:
    if audience not in _REQUIRED:
        raise ValueError('REGISTRATION_TERMS_AUDIENCE_INVALID')
    registry = _load_registry()
    entries = {x['id']: x for x in registry['documents']}
    if len(entries) != len(registry['documents']):
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    documents = []
    ready = registry.get('release_status') == 'APPROVED' and not registry.get('unresolved')
    ready = ready and all(registry.get(key) for key in _REQUIRED_RELEASE_FIELDS)
    operator = registry.get('operator') or {}
    contact = registry.get('contact_channels') or {}
    ready = ready and all(operator.get(k) for k in ('legal_name', 'registration_address', 'unified_social_credit_code'))
    ready = ready and contact.get('delivery_verified') is True
    for ident in _REQUIRED[audience]:
        if ident not in entries:
            raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
        item = entries[ident]
        doc = _document(registry, ident, item['version'])
        approval = item.get('approval') or {}
        approved = (item['status'] == 'APPROVED' and '待确认草稿｜版本' not in doc['content'] and
                    'draft' not in item['version'].lower() and
                    approval.get('sha256') == doc['sha256'] and
                    all(approval.get(k) for k in ('reviewer', 'approved_at', 'evidence_ref')))
        try:
            effective = datetime.fromisoformat(item.get('effective_at') or '')
            approved_at = datetime.fromisoformat(approval.get('approved_at') or '')
            now = datetime.now(timezone.utc)
            approved = (approved and effective.tzinfo is not None and effective <= now and
                        approved_at.tzinfo is not None and approved_at <= now)
        except (TypeError, ValueError):
            approved = False
        ready = ready and approved
        documents.append({k: v for k, v in doc.items() if k != 'content'})
    return {'audience': audience, 'status': 'APPROVED' if ready else 'DRAFT',
            'acceptance_enabled': bool(ready), 'enabled': bool(ready),
            'versions': {x['id']: x['version'] for x in documents},
            'term_hashes': {x['id']: x['sha256'] for x in documents},
            'documents': documents, 'unresolved': list(registry.get('unresolved') or [])}


def require_registration_terms_ready(audience: str) -> dict:
    status = registration_terms_status(audience)
    if not status['acceptance_enabled']:
        raise ValueError('REGISTRATION_TERMS_NOT_READY')
    return status


def account_registration_terms_status(audience: str) -> dict:
    """Account-creation policy: exact registered bytes, without downstream readiness gates."""
    if audience not in _ACCOUNT_REQUIRED:
        raise ValueError('REGISTRATION_TERMS_AUDIENCE_INVALID')
    registry = _load_registry()
    entries = {x['id']: x for x in registry['documents']}
    if len(entries) != len(registry['documents']):
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    documents = []
    formal_ready = registry.get('release_status') == 'APPROVED'
    for ident in _ACCOUNT_REQUIRED[audience]:
        if ident not in entries:
            raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
        item = entries[ident]
        doc = _document(registry, ident, item['version'])
        documents.append({k: v for k, v in doc.items() if k != 'content'})
        approval = item.get('approval') or {}
        formal_ready = formal_ready and (
            item.get('status') == 'APPROVED'
            and approval.get('sha256') == doc['sha256']
            and all(approval.get(k) for k in ('reviewer','approved_at','evidence_ref'))
        )
    return {
        'audience': audience,
        'status': 'APPROVED' if formal_ready else 'DRAFT',
        'acceptance_enabled': True,
        'enabled': True,
        'account_stage': True,
        'versions': {x['id']: x['version'] for x in documents},
        'term_hashes': {x['id']: x['sha256'] for x in documents},
        'documents': documents,
        'deferred': list(_ACCOUNT_DEFERRED[audience]),
        'formal_approval_pending': not formal_ready,
        'unresolved': list(registry.get('unresolved') or []),
    }


def require_account_registration_terms_ready(audience: str) -> dict:
    return account_registration_terms_status(audience)
