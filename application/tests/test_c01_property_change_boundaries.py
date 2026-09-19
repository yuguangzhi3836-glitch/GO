"""Supplier inputs must preserve the existing approval and draft boundaries."""
import pytest
from sqlalchemy import func, select

from go_hotel.db.models import HotelPartnerImportJobRow, HotelPartnerPropertyRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc


def property_row():
    return svc.create_property('c01-owner', 'c01-actor', {
        'name_zh': 'Original Hotel', 'property_type': 'HOTEL',
        'legal': {'company': 'Original Legal'}, 'address': {'city': 'Original City'},
        'brand_name': 'Original Brand', 'group_name': 'Original Group',
    })


@pytest.mark.parametrize('field,value,group', [
    ('legal', {'company': 'Changed Legal'}, 'LEGAL'),
    ('address', {'city': 'Changed City'}, 'ADDRESS'),
    ('brand_name', 'Changed Brand', 'BRAND'),
    ('group_name', 'Changed Group', 'BRAND'),
])
def test_api_field_names_require_review_and_keep_mixed_patch_atomic(field, value, group):
    prop = property_row()
    before = svc.graph('c01-owner', prop['property_id'])['property']
    body = {field: value, 'contacts': {'phone': 'must-be-staged'}}
    result = svc.patch_property('c01-owner', 'c01-actor', prop['property_id'], body)
    assert result['mode'] == 'CHANGE_REQUEST'
    assert result['change_request']['field_group'] == group
    assert result['change_request']['proposed_value_json'] == body
    current = svc.graph('c01-owner', prop['property_id'])['property']
    assert current == before


@pytest.mark.parametrize('state', ['PUBLISHED', 'UNDER_REVIEW'])
def test_import_cannot_change_non_draft_library_or_claim_it_is_draft(state):
    prop = property_row()
    with SessionLocal.begin() as session:
        session.get(HotelPartnerPropertyRow, prop['property_id']).publication_state = state
    with pytest.raises(ValueError, match='PROPERTY_IMPORT_REQUIRES_DRAFT'):
        svc.one_click_import('c01-owner', 'c01-actor', prop['property_id'], {
            'provider': 'CTRIP', 'method': 'DATA_EXPORT',
            'hotel_package': {'hotel': {'legal': {'company': 'Unreviewed Import'}}},
        }, 'import-non-draft')
    with SessionLocal() as session:
        current = session.get(HotelPartnerPropertyRow, prop['property_id'])
        assert current.legal_json == prop['legal_json']
        assert current.publication_state == state
        assert current.version == prop['version']
        assert session.scalar(select(func.count()).select_from(HotelPartnerImportJobRow)) == 0


def test_draft_import_and_low_risk_contact_edit_remain_available():
    prop = property_row()
    result = svc.one_click_import('c01-owner', 'c01-actor', prop['property_id'], {
        'provider': 'CTRIP', 'method': 'DATA_EXPORT',
        'hotel_package': {'hotel': {'legal': {'company': 'Draft Legal'}}},
    }, 'import-draft')
    assert result['publication_state'] == 'DRAFT'
    updated = svc.patch_property('c01-owner', 'c01-actor', prop['property_id'], {'contacts': {'phone': '555'}})
    assert updated['mode'] == 'IMMEDIATE'
    assert updated['property']['legal_json'] == {'company': 'Draft Legal'}
