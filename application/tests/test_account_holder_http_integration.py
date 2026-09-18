from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from go_hotel.db.models import HotelPartnerPropertyRow, IdentityUserRow
from go_hotel.db.session import SessionLocal
from go_hotel.security.deps import current_principal
from go_hotel.security.service import Principal


def principal(user, actor='CONSUMER', permissions=()):
    return Principal(user, user, actor, None, [], 'isolated-session', set(permissions))


def test_external_order_http_roundtrip_preserves_owner_and_connector_authority(client):
    from go_hotel.main import app
    holder = [principal('http-owner')]
    app.dependency_overrides[current_principal] = lambda: holder[0]
    try:
        body = {'provider': 'BOOKING', 'external_order_id': 'HTTP-1001',
                'vertical': 'HOTEL', 'lifecycle_state': 'CONFIRMED', 'payment_state': 'PAID'}
        created = client.post('/v1/consumer/unified-trips/external-orders', json=body)
        assert created.status_code == 201, created.text
        item = created.json()['data']
        assert item['lifecycle_state'] == 'MANUAL_REVIEW'
        assert item['payment_state'] == 'UNKNOWN_EXTERNAL_STATE'
        listed = client.get('/v1/consumer/unified-trips')
        assert listed.status_code == 200, listed.text
        assert any(row['order_id'] == item['order_id'] for row in listed.json()['data']['items'])

        holder[0] = principal('other-owner')
        other = client.get('/v1/consumer/unified-trips')
        assert not other.json()['data']['items']
        denied = client.get('/v1/consumer/unified-trips/' + item['consumer_unified_lifecycle_id'])
        assert denied.status_code in {403, 404, 409}
        assert 'http-owner' not in denied.text

        event = body | {'account_id': 'http-owner', 'adapter_id': 'booking-orders-v1',
                        'refund_state': 'NOT_REQUESTED', 'source_event_id': 'http-event-1',
                        'source_updated_at': (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                        'evidence_reference': 'adapter://isolated-evidence',
                        'servicing_deep_link': 'https://secure.booking.com/myreservations.html'}
        holder[0] = principal('order-ops', 'GO_ADMIN', {'admin:orders'})
        denied = client.post('/internal/v1/consumer-lifecycle/external-orders/project', json=event)
        assert denied.status_code == 403, denied.text
        holder[0] = principal('connector', 'GO_ADMIN', {'admin:connector'})
        projected = client.post('/internal/v1/consumer-lifecycle/external-orders/project', json=event)
        assert projected.status_code == 200, projected.text
        verified = projected.json()['data']
        assert verified['order_id'] == item['order_id']
        assert verified['lifecycle_state'] == 'CONFIRMED'
        assert verified['facts_json']['support_owner'] == 'BOOKING'
        replay = client.post('/internal/v1/consumer-lifecycle/external-orders/project', json=event)
        assert replay.status_code == 200 and replay.json()['data']['stale_ignored'] is True
    finally:
        app.dependency_overrides.pop(current_principal, None)


def test_supplier_bff_registration_keeps_terms_and_creates_owned_draft(client):
    from go_hotel.api.routes.bff import SUPPLIER_REGISTRATION_TERMS
    body = {'email': 'http-supplier@example.test', 'password': 'isolated-pass-123',
            'organization_name': 'HTTP Test Hotel', 'contact_name': 'Test Owner',
            'accepted_terms': False, 'term_versions': SUPPLIER_REGISTRATION_TERMS}
    rejected = client.post('/bff/auth/supplier/register', json=body)
    assert rejected.status_code == 422, rejected.text
    with SessionLocal() as session:
        assert session.scalar(select(IdentityUserRow).where(IdentityUserRow.username == body['email'])) is None
    response = client.post('/bff/auth/supplier/register', json=body | {'accepted_terms': True})
    assert response.status_code == 201, response.text
    data = response.json()['data']
    with SessionLocal() as session:
        prop = session.get(HotelPartnerPropertyRow, data['property_id'])
        assert prop.supplier_id == data['supplier_id']
        assert prop.publication_state == 'DRAFT'
        assert prop.operations_json['ownership']['verification_required_before_publication'] is True
