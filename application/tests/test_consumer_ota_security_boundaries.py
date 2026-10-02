from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as lifecycle
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as partner
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault
from go_hotel.security.deps import connector_admin_principal
from go_hotel.security.service import Principal


def test_consumer_provider_authorization_rejects_local_or_active_content_url(monkeypatch):
    for value in ('http://accounts.ctrip.com/authorize', 'https://127.0.0.1/authorize', 'javascript:alert(1)'):
        monkeypatch.setenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL', value)
        with pytest.raises(ValueError, match='PROFILE_PROVIDER_AUTHORIZATION_URL_INVALID'):
            vault.create_provider_connection('consumer-security', {
                'provider':'CTRIP', 'method':'OFFICIAL_AUTHORIZATION', 'account_holder_confirmed':True,
            })


def test_external_order_minimizes_identifiers_and_rejects_secret_bearing_link():
    item=lifecycle.import_external_order('consumer-minimized', {
        'provider':'CTRIP', 'external_order_id':'C-SECRET-1001', 'vertical':'HOTEL',
        'facts':{'hotel_name':'Safe Hotel','passport_number':'E12345678','access_token':'secret'},
    })
    facts=item['facts_json']
    assert facts['external_order_id_masked'].endswith('1001')
    assert 'external_order_id' not in facts and 'passport_number' not in facts and 'access_token' not in facts
    with pytest.raises(ValueError, match='INVALID_EXTERNAL_SERVICE_LINK'):
        lifecycle.import_external_order('consumer-link-secret', {
            'provider':'BOOKING','external_order_id':'B-1','vertical':'HOTEL',
            'lifecycle_state':'CONFIRMED','payment_state':'PAID','refund_state':'NOT_REQUESTED',
            'source_event_id':'evt-secret','source_updated_at':'2026-09-18T10:00:00Z',
            'evidence_reference':'adapter://opaque','servicing_deep_link':'booking://orders/B-1?access_token=secret',
        },trusted_provider=True,adapter_id='booking-orders-v1')
    with pytest.raises(ValueError, match='INVALID_EXTERNAL_SERVICE_LINK'):
        lifecycle.import_external_order('consumer-link-fragment', {
            'provider':'BOOKING','external_order_id':'B-1F','vertical':'HOTEL',
            'lifecycle_state':'CONFIRMED','payment_state':'PAID','refund_state':'NOT_REQUESTED',
            'source_event_id':'evt-fragment','source_updated_at':'2026-09-18T10:00:00Z',
            'evidence_reference':'adapter://opaque','servicing_deep_link':'booking://orders/B-1#access_token=secret',
        },trusted_provider=True,adapter_id='booking-orders-v1')


def test_official_order_rejects_future_dated_event():
    future=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match='EXTERNAL_ORDER_SOURCE_TIME_INVALID'):
        lifecycle.import_external_order('consumer-future', {
            'provider':'BOOKING','external_order_id':'B-2','vertical':'HOTEL',
            'lifecycle_state':'CONFIRMED','payment_state':'PAID','refund_state':'NOT_REQUESTED',
            'source_event_id':'evt-future','source_updated_at':future,'evidence_reference':'adapter://opaque',
        },trusted_provider=True,adapter_id='booking-orders-v1')


def test_room_media_cannot_bypass_rights_gate():
    prop=partner.create_property('security-supplier','security-owner',{
        'name_zh':'安全测试酒店','property_type':'HOTEL',
    })
    body={'name_zh':'大床房','physical_room_count':1,
        'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0},
        'media':[{'url':'https://media.example.test/room.jpg'}]}
    with pytest.raises(ValueError, match='MEDIA_RIGHTS_EVIDENCE_REQUIRED'):
        partner.create_room_type('security-supplier','security-owner',prop['property_id'],body)
    body['media_rights']={'status':'DISTRIBUTION_LICENSE','rights_holder':'Hotel Ltd',
        'evidence_reference':'contract://expired','usage_scope':['DISTRIBUTE_ON_GO'],
        'applies_to_all_assets':True,'expires_at':'2020-01-01T00:00:00Z'}
    with pytest.raises(ValueError, match='MEDIA_RIGHTS_EXPIRED'):
        partner.create_room_type('security-supplier','security-owner',prop['property_id'],body)


def test_property_operations_media_cannot_bypass_rights_gate():
    prop=partner.create_property('security-supplier','security-owner',{
        'name_zh':'安全测试酒店','property_type':'HOTEL',
    })
    with pytest.raises(ValueError, match='MEDIA_RIGHTS_EVIDENCE_REQUIRED'):
        partner.patch_property('security-supplier','security-owner',prop['property_id'],{
            'operations':{'media_candidates':[{'url':'https://media.example.test/property.jpg'}]},
        })


def test_supplier_authorization_rejects_private_destination(monkeypatch):
    monkeypatch.setenv('GO_CTRIP_SUPPLIER_AUTHORIZATION_URL','https://10.0.0.2/oauth/authorize')
    prop=partner.create_property('security-supplier','security-owner',{
        'name_zh':'安全测试酒店','property_type':'HOTEL',
    })
    with pytest.raises(ValueError, match='SUPPLIER_PROVIDER_AUTHORIZATION_URL_INVALID'):
        partner.one_click_import('security-supplier','security-owner',prop['property_id'],{
            'provider':'CTRIP','method':'OFFICIAL_AUTHORIZATION',
        })


def test_official_adapter_projection_requires_connector_admin_permission():
    order_ops=Principal('ops','ops','GO_ADMIN',None,['GO_ORDER_OPS'],'session',{'admin:read','admin:orders'})
    with pytest.raises(HTTPException, match='403'):
        connector_admin_principal(order_ops)
    connector=Principal('connector','connector','GO_ADMIN',None,['GO_CONNECTOR'],'session',{'admin:read','admin:connector'})
    assert connector_admin_principal(connector) is connector


def test_property_creation_cannot_bypass_media_rights_gate():
    with pytest.raises(ValueError, match='MEDIA_RIGHTS_EVIDENCE_REQUIRED'):
        partner.create_property('media-owner', 'media-user', {
            'name_zh':'Media Test', 'property_type':'HOTEL',
            'operations':{'media_candidates':[{'url':'https://media.example.test/photo.jpg'}]},
        })


@pytest.mark.parametrize('destination', [
    'https://user:password@ctrip.com/search',
    'ctrip://user:password@hotel/search',
    'https://ctrip.com/search?access_token=private',
])
def test_member_comparison_links_never_expose_credentials(monkeypatch, destination):
    from go_hotel.services.consumer_ota_comparison import consumer_ota_comparison_service
    separator = '&' if '?' in destination else '?'
    template = destination + separator + 'checkin={checkin}&checkout={checkout}&rooms={rooms}&adults={adults}&children={children}'
    monkeypatch.setenv('GO_CTRIP_CONSUMER_DEEP_LINK', template)
    result = consumer_ota_comparison_service.options('link-owner', {
        'city_code':'SHA', 'check_in':'2026-10-01', 'check_out':'2026-10-02',
        'rooms':1, 'adults':2, 'children':0, 'currency':'CNY',
    })
    provider = next(row for row in result['providers'] if row['provider']=='CTRIP')
    assert provider['deep_link'] is None
