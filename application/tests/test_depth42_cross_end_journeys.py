from contextlib import nullcontext
from ride_cancellation_fixture import synthetic_policy
"""Six real API journeys and independent money checks; not browser/device E2E."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import secrets
import pytest

from sqlalchemy import select

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    OrderRow, OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger,
    OrderSupplierFulfillmentRow as Fulfillment,
)
from go_hotel.security.service import identity_service
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault
from tests.test_master03_closure import profile
from test_sprint3a_flight import auth


def data(response):
    assert response.status_code == 200, response.text
    return response.json()['data']


def console_auth(client, supplier_id=None, login_again=False):
    username = 'journey-' + secrets.token_hex(8) + '@example.test'
    password = secrets.token_urlsafe(32)
    actor = 'SUPPLIER_USER' if supplier_id else 'GO_ADMIN'
    identity_service.create_user(username, password, actor, supplier_id,
        ['SUPPLIER_OWNER'] if supplier_id else ['GO_GOVERNANCE'])
    tokens = identity_service.login(username, password, None, 'isolated-api-journey',
        expected_actor_type=actor)
    def fresh():
        next_tokens = identity_service.login(username, password, None, 'isolated-api-relogin', expected_actor_type=actor)
        return {'Authorization': 'Bearer ' + next_tokens['access_token']}
    headers = {'Authorization': 'Bearer ' + tokens['access_token']}
    return (headers, fresh) if login_again else headers


def six_orders(client, headers):
    uid = data(client.get('/v1/consumer/me', headers=headers))['user_id']
    people = [profile(uid, name='ISOLATED JOURNEY ' + str(n)) for n in (1, 2)]
    vault.grant_consent(uid, {'traveler_id': people[0], 'purpose': 'RENTAL_BOOKING',
        'scope': ['DRIVER_LICENSE_NUMBER']})
    day = (date.today() + timedelta(days=30)).isoformat()
    end = (date.today() + timedelta(days=35)).isoformat()
    def post(path, body=None):
        return data(client.post(path, headers={**headers, 'Idempotency-Key': secrets.token_hex(16)}, json=body))
    result = {}
    hotel = post('/v1/search/hotels', {'destination': {'city_code': 'TYO'},
        'stay': {'check_in': day, 'check_out': end},
        'occupancy': {'rooms': 1, 'adults': 2, 'children': 0}, 'currency': 'CNY'})['hotels'][0]
    pb = post('/v1/offers/' + hotel['best_offer']['offer_id'] + '/prebook', {'currency': 'CNY'})
    result['HOTEL'] = post('/v1/consumer/orders', {'prebook_id': pb['prebook_id'],
        'expected_fare_rule_hash': pb['fare_rule']['offer_rule_hash'], 'fare_confirmed': True,
        'traveler_ids': people})
    legs = post('/v1/flights/journeys/search', {'trip_type': 'ROUND_TRIP', 'adults': 2,
        'legs': [{'origin': 'SHA', 'destination': 'PEK', 'departure_date': day},
                 {'origin': 'PEK', 'destination': 'SHA', 'departure_date': end}]})['legs']
    offer = post('/v1/flights/journeys/compose', {'trip_type': 'ROUND_TRIP',
        'offer_ids': [next(x['offer_id'] for x in leg['items'] if x['refund_policy']['allowed']) for leg in legs]})
    pb = post('/v1/flights/offers/' + offer['offer_id'] + '/prebook')
    result['FLIGHT'] = post('/v1/flights/orders', {'prebook_id': pb['prebook_id'], 'traveler_ids': people})
    offer = post('/v1/rail/search', {'origin_station': 'SHA', 'destination_station': 'HZH', 'travel_date': day})['items'][0]
    pb = post('/v1/rail/offers/' + offer['offer_id'] + '/prebook', {'quantity': 2})
    result['RAIL'] = post('/v1/rail/orders', {'prebook_id': pb['prebook_id'], 'traveler_ids': people})
    for vertical, base, body in [
        ('RIDE', '/v1/mobility/rides', {'pickup': 'PVG', 'dropoff': 'Bund', 'pickup_at': day + 'T10:00:00+08:00'}),
        ('RENTAL', '/v1/mobility/rentals', {'pickup_location': 'NRT', 'return_location': 'NRT',
            'pickup_at': day + 'T10:00:00+09:00', 'return_at': end + 'T10:00:00+09:00'}),
    ]:
        with synthetic_policy() if vertical == 'RIDE' else nullcontext():
            offer = post(base + '/search', body)['items'][0]
            accepted = {'cancellation_policy_hash': offer['cancellation']['policy_hash']} if vertical == 'RIDE' else {}
            result[vertical] = post(base + '/orders', {**body, 'offer_id': offer['offer_id'], 'traveler_ids': people[:1], **accepted})
    offer = post('/v1/attractions/search', {'destination': '东京', 'visit_date': day})['items'][0]
    params = {'offer_id': offer['offer_id'], 'visit_date': day, 'session_time': offer.get('session_time'), 'quantity': 2}
    pb = post('/v1/attractions/prebook', params)
    result['ATTRACTION'] = post('/v1/attractions/orders', {**params, 'prebook_id': pb['prebook_id'], 'traveler_ids': people})
    return result


def test_six_vertical_paid_refunded_money_and_three_actor_same_order(client):
    consumer = auth(client, 'depth42-journey@example.test')
    stranger = auth(client, 'depth42-other@example.test')
    orders = six_orders(client, consumer)
    administrator, admin_relogin = console_auth(client, login_again=True)
    unrelated_supplier = console_auth(client, 'depth42-unrelated')
    observations = []
    for vertical, order in orders.items():
        oid = order['order_id']
        pay_path = f'/v1/consumer/checkout/{vertical}/{oid}'
        pay_body = {'mode': 'CONTRACT_SIMULATOR', 'expected_amount_minor': order['total_amount_minor'], 'currency': 'CNY'}
        paid = data(client.post(pay_path, headers={**consumer, 'Idempotency-Key': 'depth42-pay-' + oid}, json=pay_body))
        assert paid['status'] in {'CONFIRMED', 'TICKETED'}, (vertical, paid)
        assert client.post(pay_path, headers={**stranger, 'Idempotency-Key': 'other-' + oid}, json=pay_body).status_code == 404
        if vertical == 'HOTEL':
            quote = data(client.post(f'/v1/orders/{oid}/cancellation-quote', headers=consumer))
            refund_path = f'/v1/orders/{oid}/cancel'
            body = {'cancellation_quote_id': quote['quote_id'], 'quote_hash': quote['quote_hash'], 'confirmed': True}
        else:
            base = {'FLIGHT': '/v1/flights', 'RAIL': '/v1/rail', 'RIDE': '/v1/mobility',
                    'RENTAL': '/v1/mobility', 'ATTRACTION': '/v1/attractions'}[vertical]
            quote = data(client.get(f'{base}/orders/{oid}/refund-quote', headers=consumer))
            refund_path = f'{base}/orders/{oid}/refund-confirmed'
            body = {'quote_hash': quote['quote_hash'], 'confirmed': True}
        assert client.post(refund_path, headers=consumer, json={**body, 'confirmed': False}).status_code in {409, 422}
        assert client.post(refund_path, headers=stranger, json=body).status_code == 404
        headers = {**consumer, 'Idempotency-Key': 'depth42-refund-' + oid}
        receipt = data(client.post(refund_path, headers=headers, json=body))
        assert data(client.post(refund_path, headers=headers, json=body)) == receipt
        with SessionLocal() as session:
            intents = session.scalars(select(Intent).where(Intent.business_type == vertical + '_ORDER', Intent.business_id == oid)).all()
            assert len(intents) == 1
            intent = intents[0]
            moves = session.scalars(select(Movement).where(Movement.root_payment_intent_id == intent.payment_intent_id)).all()
            captures = [m for m in moves if m.movement_type == 'CAPTURE']
            refunds = [m for m in moves if m.movement_type == 'REFUND']
            assert len(captures) == len(refunds) == 1, (vertical, len(captures), len(refunds))
            assert captures[0].amount_minor == order['total_amount_minor']
            assert refunds[0].amount_minor == quote['refund_amount_minor']
            assert refunds[0].parent_movement_id == captures[0].money_movement_id
            assert all(m.state == 'CONFIRMED' and m.currency == quote['currency'] for m in moves)
            for move in moves:
                entries = session.scalars(select(Ledger).where(Ledger.transaction_id == move.money_movement_id)).all()
                if move.movement_type in {'AUTHORIZATION', 'RELEASE'}:
                    assert not entries
                    continue
                assert len(entries) == 2 and {e.direction for e in entries} == {'DEBIT', 'CREDIT'}
                assert all(e.amount_minor == move.amount_minor and e.currency == move.currency for e in entries)
            owner = session.get(OrderRow, oid).supplier_id if vertical == 'HOTEL' else session.scalar(
                select(Fulfillment).where(Fulfillment.payment_intent_id == intent.payment_intent_id)).supplier_id
        supplier, supplier_relogin = console_auth(client, owner, login_again=True)
        trip = next(x for x in data(client.get('/v1/consumer/unified-trips', headers=consumer))['items'] if x['order_id'] == oid)
        assert trip['supplier_id'] == owner
        observations.append({'vertical': vertical, 'order_id': oid, 'supplier_id': owner,
            'paid_minor': order['total_amount_minor'], 'refund_minor': quote['refund_amount_minor'],
            'currency': quote['currency'], 'native_status': trip['native_status'],
            'refund_state': trip['refund_state'], 'money_rows_verified': len(moves)})
        observations[-1]['actor_views'] = {}
        # Same order is available in each role's list and final detail.
        observations[-1]['supplier_listed'] = any(x['order_id'] == oid for x in
            data(client.get('/v1/supplier/transaction-orders', headers=supplier))['items'])
        observations[-1]['admin_listed'] = any(x['order_id'] == oid for x in
            data(client.get(f'/internal/v1/admin/operations/verticals/{vertical}', headers=administrator))['orders'])
        for actor, prefix in [(consumer, '/v1/consumer'), (supplier, '/v1/supplier'), (administrator, '/internal/v1/admin')]:
            response = client.get(f'{prefix}/transaction-orders/{vertical}/{oid}', headers=actor)
            observations[-1][prefix + '_journey_status'] = response.status_code
            if response.status_code == 200:
                view = data(response)
                assert view['order']['order_id'] == oid
                assert view['original_payment']['captured_minor'] == order['total_amount_minor']
                assert view['original_payment']['refunded_minor'] == quote['refund_amount_minor']
                assert view['original_payment']['ledger_balanced']
                assert view['order']['status'] == trip['native_status']
                assert view['order']['currency'] == quote['currency']
                assert view['original_payment']['net_minor'] == order['total_amount_minor'] - quote['refund_amount_minor']
                assert data(client.get(f'{prefix}/transaction-orders/{vertical}/{oid}', headers=actor)) == view
                if prefix == '/v1/consumer':
                    tokens = data(client.post('/v1/mobile/auth/login', json={'email':'depth42-journey@example.test','password':'StrongPass123!'}))
                    fresh = {'Authorization':'Bearer '+tokens['access_token']}
                    client.cookies.clear()
                else:
                    fresh = supplier_relogin() if prefix == '/v1/supplier' else admin_relogin()
                assert data(client.get(f'{prefix}/transaction-orders/{vertical}/{oid}', headers=fresh)) == view
                observations[-1]['actor_views'][prefix] = {'final':view,'refresh':'PASS','relogin':'PASS'}
        assert client.get(f'/v1/supplier/transaction-orders/{vertical}/{oid}', headers=unrelated_supplier).status_code == 404
        assert client.get(f'/v1/consumer/transaction-orders/{vertical}/{oid}', headers=stranger).status_code == 404
    print('DEPTH42_JOURNEYS=' + json.dumps(observations, ensure_ascii=False))
    if os.getenv('GO_JOURNEY_EVIDENCE'):
        Path(os.environ['GO_JOURNEY_EVIDENCE']).write_text(json.dumps(observations, indent=2) + '\n')
    assert len(data(client.get('/v1/consumer/unified-trips', headers=consumer))['items']) == 6
    assert all(x['supplier_listed'] and x['admin_listed'] for x in observations), observations
    assert all(x['refund_state'] == 'REFUND_COMPLETED' for x in observations), observations
    assert all(all(x[p + '_journey_status'] == 200 for p in ['/v1/consumer', '/v1/supplier', '/internal/v1/admin']) for x in observations)


def test_go_trip_includes_all_six_unpaid_and_terminal_orders_without_other_accounts(client):
    from go_hotel.services.transaction_order_view import ORDERS as MODELS
    consumer = auth(client, 'all-trips-depth42@example.test')
    orders = six_orders(client, consumer)
    first = data(client.get('/v1/consumer/unified-trips', headers=consumer))['items']
    assert {x['order_id'] for x in first} == {x['order_id'] for x in orders.values()}
    assert all(x['native_status'] == 'PAYMENT_PENDING' and x['navigation'] for x in first)
    # Read-model fixtures cover historical states without executing or faking money.
    states = ['CANCELLED', 'REFUNDED', 'REFUND_PENDING', 'COMPLETED', 'PAYMENT_PENDING', 'FULFILLED']
    with SessionLocal.begin() as session:
        for (vertical, order), status in zip(orders.items(), states):
            session.get(MODELS[vertical], order['order_id']).status = status
    rows = data(client.get('/v1/consumer/unified-trips', headers=consumer))['items']
    assert {x['order_id'] for x in rows} == {x['order_id'] for x in orders.values()}
    assert {x['native_status'] for x in rows} == set(states)
    assert all(x['navigation']['order_id'] == x['order_id'] for x in rows)
    other = auth(client, 'all-trips-other-depth42@example.test')
    assert data(client.get('/v1/consumer/unified-trips', headers=other))['items'] == []


@pytest.mark.parametrize('corruption', ['ledger', 'currency', 'pending', 'projection_owner'])
def test_money_uncertainty_and_projection_cannot_grant_supplier_ownership(client, corruption):
    from test_depth33_mobility_refund_consent import booked
    from go_hotel.db.models import ConsumerUnifiedLifecycleRow as Life
    from go_hotel.services.transaction_order_view import snapshot as detail, supplier_orders as list_orders
    svc, owner, oid = booked('RIDE')
    with SessionLocal.begin() as session:
        intent = session.scalar(select(Intent).where(Intent.business_type == 'RIDE_ORDER', Intent.business_id == oid))
        supplier_id = intent.payee_id
        cap = session.scalar(select(Movement).where(Movement.root_payment_intent_id == intent.payment_intent_id, Movement.movement_type == 'CAPTURE'))
        if corruption == 'ledger':
            session.delete(session.scalar(select(Ledger).where(Ledger.transaction_id == cap.money_movement_id)))
        elif corruption == 'currency': cap.currency = 'USD'
        elif corruption == 'pending': cap.state = 'UNKNOWN_EXTERNAL_STATE'
        else: session.scalar(select(Life).where(Life.order_id == oid)).supplier_id = 'intruder'
    with pytest.raises(ValueError, match='ORDER_NOT_FOUND'):
        detail('RIDE', oid, supplier_id='intruder')
    assert list_orders('intruder')['items'] == []
    view = detail('RIDE', oid, supplier_id=supplier_id)
    if corruption == 'projection_owner':
        assert view['original_payment']['ledger_balanced']
    else:
        assert not view['original_payment']['ledger_balanced']
        assert view['original_payment']['reconciliation_required']


def test_hotel_refund_interruption_keeps_trip_pending_until_original_money_completes(client, monkeypatch):
    from test_depth14_cash_fare_api import signed_booking
    from go_hotel.services import hosted_money as funds
    headers, oid = signed_booking(client)
    q = data(client.post(f'/v1/orders/{oid}/cancellation-quote', headers=headers))
    body = {'cancellation_quote_id': q['quote_id'], 'quote_hash': q['quote_hash'], 'confirmed': True}
    original = funds.money.create_in_session
    def failed(session, intent_id, request, key, actor):
        if request['movement_type'] == 'REFUND': raise ValueError('ISOLATED_REFUND_INTERRUPTION')
        return original(session, intent_id, request, key, actor)
    with monkeypatch.context() as patch:
        patch.setattr(funds.money, 'create_in_session', failed)
        assert client.post(f'/v1/orders/{oid}/cancel', headers=headers, json=body).status_code != 200
    item = next(x for x in data(client.get('/v1/consumer/unified-trips', headers=headers))['items'] if x['order_id'] == oid)
    assert item['native_status'] == 'CANCELLED' and item['refund_state'] == 'REFUND_PROCESSING'
    op = data(client.get(f'/v1/orders/{oid}/cash-after-sales', headers=headers))
    data(client.post(f'/v1/orders/{oid}/cash-after-sales/{op["operation_id"]}/reconcile', headers=headers))
    item = next(x for x in data(client.get('/v1/consumer/unified-trips', headers=headers))['items'] if x['order_id'] == oid)
    assert item['refund_state'] == 'REFUND_COMPLETED'
