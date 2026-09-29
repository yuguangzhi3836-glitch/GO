import os
os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/go_partner_selected_import_test.db')

import pytest
from go_hotel.db.session import engine
from go_hotel.db.models import Base
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc

SID = 'selected-import-supplier'
ACT = 'hotel-owner'


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def property_and_body():
    prop = svc.create_property(SID, ACT, {
        'name_zh': '酒店自有名称', 'property_type': 'HOTEL',
        'address': {'city': 'Harbin'}, 'contacts': {'phone': 'original'},
        'operations': {'ownership': {'status': 'DECLARED'}, 'media_candidates': []},
    })
    body = {'provider': 'CTRIP', 'method': 'DATA_EXPORT',
        'selected_fields': ['hotel.contacts'], 'hotel_package': {
            'hotel': {'name_zh': '未选择名称', 'contacts': {'phone': 'new'},
                      'ownership': {'status': 'VERIFIED'}, 'source_kind': 'OFFICIAL'},
            'room_types': [{'invalid': 'not selected'}],
            'media': [{'url': 'https://example.test/not-selected.jpg'}],
        }}
    return prop['property_id'], body


def test_selected_contact_import_preserves_unselected_hotel_rooms_media_and_ownership():
    pid, body = property_and_body()
    result = svc.one_click_import(SID, ACT, pid, body, 'selected-contact')
    graph = svc.graph(SID, pid)
    prop = graph['property']
    assert prop['name_zh'] == '酒店自有名称'
    assert prop['address_json'] == {'city': 'Harbin'}
    assert prop['contacts_json'] == {'phone': 'new'}
    assert graph['room_types'] == []
    assert prop['operations_json']['media_candidates'] == []
    assert prop['operations_json']['ownership'] == {'status': 'DECLARED'}
    assert result['media_candidates'] == result['room_types_created'] == 0
    assert result['mapping']['hotel_fields'] == ['contacts']
    source = prop['operations_json']['import_field_sources']
    assert set(source) == {'hotel.contacts'}
    assert source['hotel.contacts']['source_kind'] == result['source_kind'] == 'OTA_IMPORT'
    assert source['hotel.contacts']['provider'] == 'CTRIP'
    assert source['hotel.contacts']['import_job_id'] == result['import_job_id']


@pytest.mark.parametrize('selection,error', [
    ([], 'IMPORT_SELECTION_REQUIRED'),
    ('hotel.contacts', 'IMPORT_SELECTION_REQUIRED'),
    (['hotel.ownership'], 'INVALID_IMPORT_SELECTION'),
    (['hotel.contacts.phone'], 'INVALID_IMPORT_SELECTION'),
    ([{}], 'INVALID_IMPORT_SELECTION'),
    (['hotel.brand_name'], 'IMPORT_SELECTED_FIELD_MISSING'),
])
def test_invalid_selection_cannot_mutate_property(selection, error):
    pid, body = property_and_body()
    before = svc.graph(SID, pid)
    body['selected_fields'] = selection
    with pytest.raises(ValueError, match=error):
        svc.one_click_import(SID, ACT, pid, body)
    assert svc.graph(SID, pid) == before


def test_unselected_credentials_still_rejected_before_any_mutation():
    pid, body = property_and_body()
    body['hotel_package']['media'][0]['cookie'] = 'must-not-persist'
    with pytest.raises(ValueError, match='OTA_CREDENTIALS_NOT_ACCEPTED'):
        svc.one_click_import(SID, ACT, pid, body)
    assert svc.graph(SID, pid)['property']['contacts_json'] == {'phone': 'original'}


def test_selection_stays_tenant_bound_and_replay_cannot_change_selection():
    pid, body = property_and_body()
    with pytest.raises(ValueError, match='PROPERTY_NOT_FOUND'):
        svc.one_click_import('other-supplier', ACT, pid, body)
    first = svc.one_click_import(SID, ACT, pid, body, 'same-key')
    replay = svc.one_click_import(SID, ACT, pid, body, 'same-key')
    assert replay['idempotent_replay'] is True
    assert replay['import_job_id'] == first['import_job_id']
    body['selected_fields'] = ['hotel.name_zh']
    with pytest.raises(ValueError, match='IDEMPOTENCY_PAYLOAD_MISMATCH'):
        svc.one_click_import(SID, ACT, pid, body, 'same-key')
    assert svc.graph(SID, pid)['property']['name_zh'] == '酒店自有名称'


def test_selected_media_keeps_existing_rights_gate():
    pid, body = property_and_body()
    body['selected_fields'] = ['media']
    with pytest.raises(ValueError, match='MEDIA_RIGHTS_EVIDENCE_REQUIRED'):
        svc.one_click_import(SID, ACT, pid, body)


def test_successive_imports_preserve_other_fields_source_and_default_compatibility():
    pid, body = property_and_body()
    svc.one_click_import(SID, ACT, pid, body, 'contact-source')
    second = {'provider': 'BOOKING', 'method': 'FILE_UPLOAD',
              'hotel_package': {'hotel': {'name_en': 'Hotel English Name'}}}
    svc.one_click_import(SID, ACT, pid, second, 'name-source')
    prop = svc.graph(SID, pid)['property']
    assert prop['name_en'] == 'Hotel English Name'
    sources = prop['operations_json']['import_field_sources']
    assert sources['hotel.contacts']['provider'] == 'CTRIP'
    assert sources['hotel.name_en']['provider'] == 'BOOKING'
    assert sources['hotel.name_en']['source_kind'] == 'OTA_IMPORT'
