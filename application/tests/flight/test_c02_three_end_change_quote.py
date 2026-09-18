from datetime import date, timedelta

from go_hotel.security.service import identity_service
from tests.test_sprint3a_flight import auth, create_ticketed


def _headers(username, password):
    token = identity_service.login(username, password)
    return {'Authorization': 'Bearer ' + token['access_token']}


def test_consumer_change_quote_retry_is_idempotent_and_payload_bound(client):
    consumer = auth(client, 'c02-change-quote@example.test')
    order_id = create_ticketed(client, consumer)
    path = f'/v1/flights/orders/{order_id}/change-quote'
    key = 'c02-change-quote-retry-001'
    body = {'new_departure_date': (date.today() + timedelta(days=12)).isoformat()}

    first = client.post(path, headers={**consumer, 'Idempotency-Key': key}, json=body)
    replay = client.post(path, headers={**consumer, 'Idempotency-Key': key}, json=body)
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.json()['data']['quote_id'] == first.json()['data']['quote_id']

    changed = client.post(path, headers={**consumer, 'Idempotency-Key': key}, json={
        'new_departure_date': (date.today() + timedelta(days=13)).isoformat(),
    })
    assert changed.status_code == 409
    assert changed.json()['detail']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_flight_change_endpoints_enforce_consumer_supplier_admin_identities(client):
    consumer = auth(client, 'c02-boundary@example.test')
    order_id = create_ticketed(client, consumer)
    path = f'/v1/flights/orders/{order_id}/change-quote'
    body = {'new_departure_date': (date.today() + timedelta(days=14)).isoformat()}
    supplier = _headers('supplier_owner', 'change-me-supplier')
    admin = _headers('go_admin', 'change-me-admin')

    assert client.post(path, headers=supplier, json=body).status_code == 403
    assert client.post(path, headers=admin, json=body).status_code == 403

    quote = client.post(path, headers={**consumer, 'Idempotency-Key': 'c02-boundary-quote'}, json=body)
    assert quote.status_code == 200, quote.text
    quote_id = quote.json()['data']['quote_id']
    executed = client.post(
        f'/v1/flights/orders/{order_id}/execute-change/{quote_id}',
        headers={**consumer, 'Idempotency-Key': 'c02-boundary-execute'},
    )
    assert executed.status_code == 200, executed.text

    admin_path = f'/internal/v1/admin/flights/orders/{order_id}/external-state'
    resolution = {
        'state': 'TICKETED',
        'evidence_reference': 'isolated://c02/admin-resolution',
        'supplier_reference': 'PNR-C02-ADMIN',
        'ticket_numbers': ['990-C02-ADMIN'],
        'quote_id': quote_id,
    }
    assert client.post(admin_path, headers=consumer, json=resolution).status_code == 403
    assert client.post(admin_path, headers=supplier, json=resolution).status_code == 403
    accepted = client.post(
        admin_path,
        headers={**admin, 'Idempotency-Key': 'c02-admin-resolution'},
        json=resolution,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['data']['status'] == 'TICKETED'
    assert accepted.json()['data']['pnr'] == 'PNR-C02-ADMIN'
