"""Client import metadata cannot become provider authority or cross-owner links."""
import pytest

from go_hotel.db.models import ProfileImportJobRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as svc


def upload(owner):
    connection = svc.create_provider_connection(owner, {
        'provider': 'CTRIP', 'method': 'FILE_UPLOAD', 'account_holder_confirmed': True,
    })
    preview = svc.upload_provider_export(owner, connection['connection_id'], {
        'account_holder_confirmed': True, 'items': [],
    })['preview']
    return connection, preview


def test_client_metadata_cannot_disconnect_another_users_import():
    victim = svc.create_import('victim', {'items': [], 'metadata': {'note': 'untouched'}})
    blocked = False
    try:
        forged = svc.create_import('attacker', {'items': [], 'metadata': {
            'connection_intent': True, 'import_job_id': victim['import_job_id'],
        }})
        svc.disconnect_provider_connection('attacker', forged['import_job_id'])
    except ValueError as exc:
        assert str(exc) == 'PROFILE_IMPORT_METADATA_RESERVED'
        blocked = True
    with SessionLocal() as session:
        assert session.get(ProfileImportJobRow, victim['import_job_id']).metadata_json == {'note': 'untouched'}
    assert blocked


@pytest.mark.parametrize('metadata', [
    {'connection_intent': True}, {'provider_connection_id': 'forged'},
    {'account_holder_authorized': True}, {'account_holder_verified': True},
    {'provider_account_subject_hash': 'forged'}, {'authorization_evidence_hash': 'forged'},
    {'source_disconnected': False}, {'values_deleted': False}, {'state_hash': 'forged'},
])
def test_server_managed_metadata_cannot_be_supplied_by_an_import_client(metadata):
    with pytest.raises(ValueError, match='PROFILE_IMPORT_METADATA_RESERVED'):
        svc.create_import('owner', {'items': [], 'metadata': metadata})


@pytest.mark.parametrize('other_owner', ['owner', 'another-owner'])
@pytest.mark.parametrize('delete_values', [False, True])
def test_legacy_or_corrupt_connection_pointer_must_reverse_bind_to_its_import(other_owner, delete_values):
    connection, preview = upload('owner')
    other_connection, other_preview = upload(other_owner)
    with SessionLocal.begin() as session:
        row = session.get(ProfileImportJobRow, connection['connection_id'])
        row.metadata_json = {**row.metadata_json, 'import_job_id': other_preview['import_job_id']}
    with pytest.raises(ValueError, match='PROFILE_PROVIDER_IMPORT_BINDING_INVALID'):
        svc.disconnect_provider_connection('owner', connection['connection_id'], delete_values)
    with SessionLocal() as session:
        target = session.get(ProfileImportJobRow, other_preview['import_job_id'])
        assert not target.metadata_json.get('source_disconnected')
        assert not target.metadata_json.get('values_deleted')
        assert session.get(ProfileImportJobRow, connection['connection_id']).status == 'PREVIEW_READY'
        assert session.get(ProfileImportJobRow, other_connection['connection_id']).status == 'PREVIEW_READY'


def test_ordinary_metadata_is_preserved_and_real_connection_can_still_be_deleted():
    metadata = {'note': 'user annotation', 'filename': 'travel.json', 'labels': ['family']}
    ordinary = svc.create_import('owner', {'items': [], 'metadata': metadata})
    with SessionLocal() as session:
        assert session.get(ProfileImportJobRow, ordinary['import_job_id']).metadata_json == metadata
    connection, preview = upload('owner')
    assert svc.disconnect_provider_connection('owner', connection['connection_id'], True)['status'] == 'DELETED'
    with SessionLocal() as session:
        assert session.get(ProfileImportJobRow, preview['import_job_id']).metadata_json['values_deleted'] is True
