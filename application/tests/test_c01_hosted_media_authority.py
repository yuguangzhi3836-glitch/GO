"""Media claims must not turn into rights proof or bypass hotel-scoped authority."""
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from go_hotel.db.models import (
    AuthSessionRow, HostedMediaAssetRow, HostedStaffRoleRow, IdentityUserRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.hosted_content_acceptance import (
    hosted_content_acceptance_service as svc, ident, now,
)
from go_hotel.api.routes.hosted_direct_booking import router
from test_c01_hosted_content_authority import (
    context, authenticated, approval_body, provision,
)


def claim(**changes):
    return {
        'asset_role': 'HERO', 'storage_reference': 'test://unverified/hero.jpg',
        'rights_owner': '哈尔滨敖麓谷雅酒店',
        'rights_evidence_reference': 'test://unverified/license', **changes,
    }


def count_assets():
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(HostedMediaAssetRow))


def test_media_claim_is_pending_and_never_rights_verified(context):
    hotel, _, checker, _, _ = context
    result = svc.media(hotel, claim(), checker)
    assert result['state'] == 'PENDING_RIGHTS_REVIEW'
    with SessionLocal() as s:
        assert s.get(HostedMediaAssetRow, result['media_asset_id']).state == 'PENDING_RIGHTS_REVIEW'
    assert svc.gate(hotel)['media_rights_verified'] is False


def test_readonly_http_denied_before_media_lookup_or_write():
    _, token = authenticated('readonly-media', ['GO_READ_ONLY'])
    app = FastAPI(); app.include_router(router)
    before = count_assets()
    with TestClient(app) as client:
        result = client.post('/internal/v1/hosted-direct/hotels/absent/media-assets',
            headers={'Authorization': 'Bearer ' + token}, json=claim())
    assert result.status_code == 403
    assert count_assets() == before


def test_legacy_verified_label_cannot_open_operations_gate(context):
    hotel, _, checker, _, snapshot = context
    svc.approve(snapshot['content_snapshot_id'], approval_body(snapshot), checker)
    asset_id = ident('legacy_media')
    with SessionLocal.begin() as s:
        s.add(HostedMediaAssetRow(media_asset_id=asset_id, hosted_hotel_id=hotel,
            **claim(), state='RIGHTS_VERIFIED', created_at=now()))
    result = svc.gate(hotel)
    assert result['state'] == 'BLOCKED_PENDING_CONTENT_AND_MEDIA'
    assert 'HOTEL_MEDIA_RIGHTS_AUTHORITY_UNVERIFIED' in result['blockers']
    assert result['media_rights_verified'] is False
    assert result['media_rights_state'] == 'HOLD_UNVERIFIED'
    with SessionLocal() as s:
        assert s.get(HostedMediaAssetRow, asset_id).state == 'RIGHTS_VERIFIED'


@pytest.mark.parametrize('fault', ['string', 'forged', 'readonly', 'disabled',
    'revoked_session', 'expired_session', 'unbound', 'wrong_hotel', 'binding_revoked',
    'wrong_source', 'missing_mode', 'production'])
def test_media_service_denies_untrusted_identity_without_writes(context, monkeypatch, fault):
    hotel, _, checker, binding, _ = context
    if fault == 'string': checker = 'hotel'
    elif fault == 'forged': checker = replace(checker, session_id='forged')
    elif fault == 'missing_mode': monkeypatch.delenv('GO_HOSTED_CONTENT_AUTHORITY_MODE')
    elif fault == 'production':
        from go_hotel.core.config import settings
        monkeypatch.setattr(settings, 'app_env', 'production')
    else:
        with SessionLocal.begin() as s:
            if fault == 'readonly': s.get(IdentityUserRow, checker.user_id).roles = ['GO_READ_ONLY']
            elif fault == 'disabled': s.get(IdentityUserRow, checker.user_id).status = 'DISABLED'
            elif fault == 'revoked_session': s.get(AuthSessionRow, checker.session_id).status = 'REVOKED'
            elif fault == 'expired_session':
                from datetime import timedelta
                s.get(AuthSessionRow, checker.session_id).expires_at = now() - timedelta(seconds=1)
            elif fault == 'unbound': s.delete(s.get(HostedStaffRoleRow, binding))
            elif fault == 'wrong_hotel': s.get(HostedStaffRoleRow, binding).hosted_hotel_id = 'other-hotel'
            elif fault == 'binding_revoked': s.get(HostedStaffRoleRow, binding).state = 'REVOKED'
            elif fault == 'wrong_source': s.get(HostedStaffRoleRow, binding).evidence_reference = 'caller-asserted'
    before = count_assets()
    with pytest.raises((PermissionError, ValueError)):
        svc.media(hotel, claim(), checker)
    assert count_assets() == before


@pytest.mark.parametrize('changes', [
    {'state': 'RIGHTS_VERIFIED'}, {'approved_by': 'hotel'},
    {'rights_evidence_reference': ' '}, {'storage_reference': 123},
    {'rights_owner': 'other'}, {'asset_role': 'ROOM'},
    {'physical_room_key': 'not-a-hero-room'}, {'asset_role': ['HERO']},
    {'storage_reference': 'x' * 513}, {'rights_evidence_reference': 'x' * 513},
    {'asset_role': 'ROOM', 'physical_room_key': 'missing-room'},
])
def test_media_invalid_or_self_authorizing_fields_have_no_write(context, changes):
    hotel, _, checker, _, _ = context
    before = count_assets()
    with pytest.raises(ValueError): svc.media(hotel, claim(**changes), checker)
    assert count_assets() == before


def test_scoped_http_registration_returns_only_pending_claim(context):
    hotel, _, _, _, _ = context
    # Explicit isolated provisioning; the route uses real JWT/session dependencies.
    principal, token = authenticated('media-uploader')
    provision(hotel, principal)
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        response = client.post(f'/internal/v1/hosted-direct/hotels/{hotel}/media-assets',
            headers={'Authorization': 'Bearer ' + token}, json=claim())
    assert response.status_code == 200
    assert response.json()['data']['state'] == 'PENDING_RIGHTS_REVIEW'
    assert count_assets() == 1
