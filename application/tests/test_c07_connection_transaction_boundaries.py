"""Connection cancellation wins over late callbacks; previews publish atomically."""
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from go_hotel.db.models import ProfileImportItemRow, ProfileImportJobRow
from go_hotel.db.session import SessionLocal
from go_hotel.services import personal_travel_vault as module

svc = module.personal_travel_vault_service
USER = 'c07-connection-owner'
ITEMS = [{'entity_type': 'TRAVELER', 'traveler_ref': 'me',
          'value': {'full_name': 'Connection Owner', 'relationship_type': 'SELF'},
          'confidence_bps': 10000}]


def upload_connection():
    return svc.create_provider_connection(USER, {
        'provider': 'CTRIP', 'method': 'FILE_UPLOAD', 'account_holder_confirmed': True,
    })


def test_malformed_export_rolls_back_claim_and_allows_corrected_upload():
    connection = upload_connection()
    cid = connection['connection_id']
    with pytest.raises(ValueError, match='PROFILE_IMPORT_ENTITY_INVALID'):
        svc.upload_provider_export(USER, cid, {
            'account_holder_confirmed': True, 'items': [None],
        })
    with SessionLocal() as session:
        assert session.get(ProfileImportJobRow, cid).status == 'AWAITING_USER_UPLOAD'
        assert session.scalar(select(func.count()).select_from(ProfileImportJobRow)) == 1
    preview = svc.upload_provider_export(USER, cid, {
        'account_holder_confirmed': True, 'items': ITEMS,
    })
    assert preview['status'] == 'PREVIEW_READY'
    assert preview['preview']['item_count'] == 1


@pytest.mark.parametrize('delete_values', [False, True])
def test_disconnect_after_authorization_consume_prevents_late_preview(monkeypatch, delete_values):
    monkeypatch.setenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL', 'https://accounts.ctrip.example/authorize')
    connection = svc.create_provider_connection(USER, {
        'provider': 'CTRIP', 'account_holder_confirmed': True,
    })
    cid = connection['connection_id']
    body = {'state': parse_qs(urlparse(connection['authorization_url']).query)['state'][0],
            'account_holder_verified': True, 'provider_account_subject': 'provider-test-holder',
            'authorization_evidence_reference': 'adapter://test-only/authorization', 'items': ITEMS}
    original = module.mutation_session
    injected = False

    @contextmanager
    def interleave_disconnect():
        nonlocal injected
        with original() as session:
            yield session
        if not injected:
            injected = True
            svc.disconnect_provider_connection(USER, cid, delete_values)

    monkeypatch.setattr(module, 'mutation_session', interleave_disconnect)
    with pytest.raises(ValueError, match='PROFILE_SOURCE_DISCONNECTED'):
        svc.complete_provider_connection(cid, body)
    with SessionLocal() as session:
        connection = session.get(ProfileImportJobRow, cid)
        assert connection.status == ('DELETED' if delete_values else 'DISCONNECTED')
        assert connection.metadata_json.get('import_job_id') is None
        assert session.scalar(select(func.count()).select_from(ProfileImportItemRow)) == 0


def test_disconnect_blocks_uncommitted_preview_without_erasing_retained_values():
    connection = upload_connection()
    preview = svc.upload_provider_export(USER, connection['connection_id'], {
        'account_holder_confirmed': True, 'items': ITEMS,
    })['preview']
    svc.disconnect_provider_connection(USER, connection['connection_id'])
    with pytest.raises(ValueError, match='PROFILE_SOURCE_DISCONNECTED'):
        svc.commit_import(USER, preview['import_job_id'])
    with SessionLocal() as session:
        item = session.scalar(select(ProfileImportItemRow).where(
            ProfileImportItemRow.import_job_id == preview['import_job_id']))
        assert item.candidate_value_ciphertext is not None


def test_upload_preview_and_connection_pointer_roll_back_together(monkeypatch):
    connection = upload_connection()
    original = svc._audit

    def fail_final_audit(*args, **kwargs):
        if args[4] == 'PROFILE_PROVIDER_EXPORT_UPLOADED':
            raise RuntimeError('injected-audit-failure')
        return original(*args, **kwargs)

    monkeypatch.setattr(svc, '_audit', fail_final_audit)
    with pytest.raises(RuntimeError, match='injected-audit-failure'):
        svc.upload_provider_export(USER, connection['connection_id'], {
            'account_holder_confirmed': True, 'items': ITEMS,
        })
    with SessionLocal() as session:
        current = session.get(ProfileImportJobRow, connection['connection_id'])
        assert current.status == 'AWAITING_USER_UPLOAD'
        assert current.metadata_json.get('import_job_id') is None
        assert session.scalar(select(func.count()).select_from(ProfileImportJobRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProfileImportItemRow)) == 0


def test_deleted_connection_cannot_be_downgraded_to_disconnected():
    connection = upload_connection()
    svc.disconnect_provider_connection(USER, connection['connection_id'], True)
    replay = svc.disconnect_provider_connection(USER, connection['connection_id'], False)
    assert replay['status'] == 'DELETED'
    with SessionLocal() as session:
        row = session.get(ProfileImportJobRow, connection['connection_id'])
        assert row.metadata_json['values_deleted'] is True


@pytest.mark.parametrize('alter', [str.swapcase, lambda value: ' ' + value + ' '])
def test_authorization_state_is_an_exact_opaque_value(monkeypatch, alter):
    monkeypatch.setenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL', 'https://accounts.ctrip.example/authorize')
    monkeypatch.setattr(module.secrets, 'token_urlsafe', lambda size: 'MixedCASE_opaque-State-123')
    connection = svc.create_provider_connection(USER, {'provider': 'CTRIP', 'account_holder_confirmed': True})
    state = parse_qs(urlparse(connection['authorization_url']).query)['state'][0]
    body = {'state': alter(state), 'account_holder_verified': True,
            'provider_account_subject': 'provider-test-holder',
            'authorization_evidence_reference': 'adapter://test-only/authorization', 'items': ITEMS}
    with pytest.raises(ValueError, match='PROFILE_PROVIDER_STATE_INVALID'):
        svc.complete_provider_connection(connection['connection_id'], body)
    assert svc.complete_provider_connection(connection['connection_id'], body | {'state': state})['status'] == 'PREVIEW_READY'
