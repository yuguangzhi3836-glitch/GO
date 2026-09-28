"""Independent review probes; never modify the implementation under review."""
import pytest
from tests.test_depth48_flight_changes import booked
from go_hotel.flight.service import flight_service as flights
from tests.test_depth48_flight_changes import consent, amounts
from tests.test_flight_journey_depth import day
from go_hotel.flight import coupon_refunds as refunds
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from sqlalchemy import delete
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightCouponRow

def refund_consent(q):
    return {'quote_hash':q['quote_hash'], 'expected_refund_amount_minor':q['refund_amount_minor'],
            'currency':q['currency'], 'confirmed':True}

@pytest.mark.parametrize('terminal', [False, True])
def test_nonchange_unknown_and_failed_do_not_publish_usable_tickets(client, terminal):
    owner, order, headers = booked(client)
    oid = order['order_id']
    flights.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://independent-unknown', 'independent-ops')
    if terminal:
        flights.admin_external_state(oid, 'FAILED', 'isolated://independent-failure', 'independent-ops')
    public = client.get('/v1/flights/orders/' + oid, headers=headers)
    assert public.status_code == 200
    data = public.json()['data']
    assert data['status'] == ('FAILED' if terminal else 'UNKNOWN_EXTERNAL_STATE')
    assert data['ticket_assignments'] == [], data
    assert not any(c['usable'] for c in data['coupons']), data

def test_partial_refund_across_two_captures_recovers_after_first_money_commit(client, monkeypatch):
    owner, order, headers = booked(client, 'ONE_WAY', 2)
    oid = order['order_id']
    first, second = [c['coupon_id'] for c in order['coupons']]
    change = flights.change_quote(owner, oid, changes=[{
        'leg_index':0, 'coupon_ids':[first], 'new_departure_date':day(12)}])
    flights.execute_change(owner, oid, change['quote_id'], consent(change))
    flights.admin_external_state(oid, 'TICKETED', 'isolated://review-change', 'reviewer',
                                 'REVIEWPNR', ['REVIEW-TICKET'], change['quote_id'])
    change2 = flights.change_quote(owner, oid, changes=[{
        'leg_index':0, 'coupon_ids':[first], 'new_departure_date':day(13)}])
    flights.execute_change(owner, oid, change2['quote_id'], consent(change2))
    flights.admin_external_state(oid, 'TICKETED', 'isolated://review-change2', 'reviewer',
                                 'REVIEWPNR2', ['REVIEW-TICKET2'], change2['quote_id'])
    q = refunds.quote(owner, oid, [second])
    refunds.execute(owner, oid, q['refund_id'], refund_consent(q))
    # Second refund must span remaining initial capture and change capture.
    q = refunds.quote(owner, oid, [first])
    original = money.create
    calls = 0
    def interrupt(intent, body, key, actor):
        nonlocal calls
        if body['movement_type'] == 'REFUND':
            calls += 1
            if calls == 2:
                raise RuntimeError('INDEPENDENT_AFTER_FIRST_CAPTURE_REFUND')
        return original(intent, body, key, actor)
    monkeypatch.setattr(money, 'create', interrupt)
    with pytest.raises(RuntimeError, match='INDEPENDENT_AFTER_FIRST_CAPTURE_REFUND'):
        refunds.execute(owner, oid, q['refund_id'], refund_consent(q))
    pending = flights.order(owner, oid)
    assert pending['status'] == 'REFUND_PENDING'
    assert pending['ticket_assignments'] == []
    after_first = amounts()['REFUND']
    monkeypatch.setattr(money, 'create', original)
    result = refunds.execute(owner, oid, q['refund_id'], refund_consent(q))
    assert result['status'] == 'REFUND_COMPLETED'
    assert flights.order(owner, oid)['status'] == 'REFUNDED'
    assert amounts()['REFUND'] == order['total_amount_minor'] + change['total_due_minor'] + change2['total_due_minor'] - 40000
    assert amounts()['REFUND'] > after_first
    before_replay = amounts()
    refunds.execute(owner, oid, q['refund_id'], refund_consent(q))
    assert amounts() == before_replay

def test_historical_order_leg_change_http_remains_available(client):
    owner, order, headers = booked(client)
    oid = order['order_id']
    # Represents a historical order, for which migration creates no invented coupons.
    with SessionLocal.begin() as s:
        s.execute(delete(FlightCouponRow).where(FlightCouponRow.order_id == oid))
    response = client.post('/v1/flights/orders/' + oid + '/change-quote', headers=headers,
        json={'changes':[{'leg_index':0, 'new_departure_date':day(12)}]})
    assert response.status_code == 200, response.text

def test_old_whole_order_refund_pending_does_not_publish_usable_tickets(client, monkeypatch):
    owner, order, headers = booked(client)
    oid = order['order_id']
    from go_hotel.flight.service import vertical_money_bridge
    original_refund = vertical_money_bridge.refund_with_adjustments
    def interrupted(*args, **kwargs):
        original_refund(*args, **kwargs)
        raise RuntimeError('INDEPENDENT_WHOLE_REFUND_INTERRUPTED')
    monkeypatch.setattr(vertical_money_bridge, 'refund_with_adjustments', interrupted)
    with pytest.raises(RuntimeError, match='INDEPENDENT_WHOLE_REFUND_INTERRUPTED'):
        flights.refund(owner, oid)
    pending = flights.order(owner, oid)
    assert pending['status'] == 'REFUND_PENDING'
    assert pending['ticket_assignments'] == []
    assert not any(c['usable'] for c in pending['coupons'])
    monkeypatch.setattr(vertical_money_bridge, 'refund_with_adjustments', original_refund)
    before = amounts()
    flights.refund(owner, oid)
    assert amounts() == before
    assert flights.order(owner, oid)['status'] == 'REFUNDED'
