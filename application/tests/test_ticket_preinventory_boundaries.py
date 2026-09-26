"""Current HTTP identities and durable prebooking boundaries, no external supply."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import select

from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.flight.service import flight_service as flights
from tests.hosted_review_support import identity
from tests.test_depth48_flight_changes import booked, consent
from tests.test_sprint3b_rail import auth as rail_auth, create_ticketed
from go_hotel.rail.service import rail_service as rail


def business_facts():
    models = [m.FlightOrderRow, m.FlightPrebookRow, m.FlightChangeQuoteRow,
              m.RailOrderRow, m.RailChangeQuoteRow, m.FlightChangeResolutionRow,
              m.RailChangeResolutionRow, m.OmnichannelMoneyMovementRow,
              m.OmnichannelLedgerEntryRow, m.VerticalCapacityClaimRow,
              m.VerticalCapacityBucketRow]
    with SessionLocal() as s:
        return {model.__name__: sorted(json.dumps(
            {c.name: getattr(row, c.name) for c in model.__table__.columns},
            sort_keys=True, default=str) for row in s.scalars(select(model)))
            for model in models}


@pytest.mark.parametrize('vertical', ['FLIGHT', 'RAIL'])
@pytest.mark.parametrize('role', ['GO_READ_ONLY', 'GO_FINANCE', 'GO_TRUST'])
def test_admin_without_order_permission_cannot_resolve_ticket_money(client, vertical, role):
    if vertical == 'FLIGHT':
        owner, order, _ = booked(client)
        oid = order['order_id']
        q = flights.change_quote(owner, oid, (datetime.now().date()+timedelta(days=12)).isoformat(), 0)
        flights.execute_change(owner, oid, q['quote_id'], consent(q))
        tickets = ['ISOLATED-A', 'ISOLATED-B']
    else:
        headers = rail_auth(client)
        oid = create_ticketed(client, headers)
        with SessionLocal() as s: owner = s.get(m.RailOrderRow, oid).account_id
        q = rail.change_quote(owner, oid, '2026-10-15')
        rail.execute_change(owner, oid, q['quote_id'])
        tickets = ['ISOLATED-A']
    _, denied = identity('ticket-denied', [role])
    _, allowed = identity('ticket-operator', ['GO_ORDER_OPS'])
    route = 'flights' if vertical == 'FLIGHT' else 'rail'
    path = f'/internal/v1/admin/{route}/orders/{oid}/external-state'
    body = {'state':'TICKETED', 'evidence_reference':'isolated://ticket-boundary',
            'supplier_reference':'ISOLATED', 'ticket_numbers':tickets, 'quote_id':q['quote_id']}
    before = business_facts()
    response = client.post(path, headers=denied, json=body)
    assert response.status_code == 403, response.text
    assert business_facts() == before
    response = client.post(path, headers=allowed, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['data']['status'] == 'TICKETED'


def prebook():
    offer = flights.search('PVG', 'NRT', '2026-10-15')[0]
    return flights.prebook(offer['offer_id'])


def test_same_prebook_consumes_once_across_concurrent_retries():
    pb = prebook()
    people = [{'full_name':'ISOLATED PERSON', 'type':'ADT'}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: flights.create_order('owner', pb['prebook_id'], people), range(2)))
    assert results[0]['order_id'] == results[1]['order_id']
    assert flights.create_order('owner', pb['prebook_id'], people)['order_id'] == results[0]['order_id']
    with SessionLocal() as s:
        assert len(list(s.scalars(select(m.FlightOrderRow)))) == 1
        assert s.get(m.FlightPrebookRow, pb['prebook_id']).status == 'CONSUMED'


@pytest.mark.parametrize('mutation', ['owner', 'party'])
def test_consumed_prebook_cannot_be_rebound_to_another_owner_or_party(mutation):
    pb = prebook()
    people = [{'full_name':'ISOLATED PERSON', 'type':'ADT'}]
    flights.create_order('owner', pb['prebook_id'], people)
    before = business_facts()
    with pytest.raises(ValueError, match='CONSUMPTION_CONFLICT'):
        flights.create_order('other' if mutation == 'owner' else 'owner', pb['prebook_id'],
                            [{'full_name':'OTHER PERSON', 'type':'ADT'}] if mutation == 'party' else people)
    assert business_facts() == before


@pytest.mark.parametrize('day', ['2026-02-30', '2026-2-3', 'not-a-date'])
def test_invalid_flight_search_date_writes_no_offers(client, day):
    response = client.post('/v1/flights/search', json={'origin':'PVG','destination':'NRT','departure_date':day})
    assert response.status_code == 422, response.text
    with SessionLocal() as s: assert list(s.scalars(select(m.FlightOfferRow))) == []


def test_exact_offer_expiry_rejects_prebook_without_writes(monkeypatch):
    from go_hotel.flight import service
    frozen = datetime(2026, 10, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr(service, 'now', lambda: frozen)
    offer = flights.search('PVG','NRT','2026-10-15')[0]
    with SessionLocal.begin() as s: s.get(m.FlightOfferRow, offer['offer_id']).expires_at = frozen
    with pytest.raises(ValueError, match='EXPIRED'): flights.prebook(offer['offer_id'])
    with SessionLocal() as s: assert list(s.scalars(select(m.FlightPrebookRow))) == []


def pending_order(vertical):
    svc = flights if vertical == 'FLIGHT' else rail
    offer = svc.search('PVG' if vertical=='FLIGHT' else 'SHA', 'NRT' if vertical=='FLIGHT' else 'HZH', '2026-10-15')[0]
    pb = svc.prebook(offer['offer_id'])
    order = svc.create_order('owner', pb['prebook_id'], [{'full_name':'ISOLATED PERSON','type':'ADT'}])
    return svc, order['order_id']


def supplier_fact(oid, tickets):
    with SessionLocal() as s:
        f = s.scalar(select(m.OrderSupplierFulfillmentRow).where(m.OrderSupplierFulfillmentRow.business_id==oid))
        assert f
        fid = f.order_supplier_fulfillment_id
    return fid, {'state':'SUPPLIER_CONFIRMED', 'external_operation_id':'isolated-'+oid,
                 'supplier_confirmation_reference':'ISOLATED', 'evidence_reference':'isolated://ticket',
                 'ticket_numbers':tickets}


@pytest.mark.parametrize('vertical', ['FLIGHT','RAIL'])
def test_supplier_fact_write_rejects_readonly_admin(client, vertical):
    svc, oid = pending_order(vertical)
    svc.checkout('owner',oid,'isolated')
    fid, body = supplier_fact(oid,['ISOLATED-1'])
    _, denied = identity('readonly-fact',['GO_READ_ONLY'])
    before = business_facts()
    response = client.post(f'/internal/v1/order-supplier-fulfillments/{fid}/supplier-fact', headers=denied, json=body)
    assert response.status_code == 403, response.text
    assert business_facts() == before


@pytest.mark.parametrize('tickets', [[], ['ONE','TWO'], [''], [' PADDED ']])
def test_flight_supplier_cannot_confirm_missing_extra_or_invalid_tickets(tickets):
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as fulfillment
    svc, oid = pending_order('FLIGHT')
    svc.checkout('owner',oid,'isolated')
    fid, body = supplier_fact(oid,tickets)
    before = business_facts()
    with pytest.raises(ValueError, match='TICKETS_INVALID'):
        fulfillment.record_supplier_fact(fid,body)
    assert business_facts() == before


@pytest.mark.parametrize('vertical', ['FLIGHT','RAIL'])
def test_delayed_checkout_writeback_does_not_regress_confirmed_tickets(monkeypatch,vertical):
    from threading import Event, current_thread
    from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as fulfillment
    svc, oid = pending_order(vertical)
    original = bridge.checkout_contract
    entered, finish = Event(), Event()
    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        if current_thread().name.startswith('delayed-checkout'):
            entered.set()
            assert finish.wait(15)
        return result
    monkeypatch.setattr(bridge,'checkout_contract',paused)
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='delayed-checkout') as pool:
        first = pool.submit(svc.checkout,'owner',oid,'isolated')
        try:
            assert entered.wait(15)
            svc.checkout('owner',oid,'isolated')
            fid, body = supplier_fact(oid,['ISOLATED-1'])
            fulfillment.record_supplier_fact(fid,body)
            assert svc.order('owner',oid)['status']=='TICKETED'
        finally:
            finish.set()
        assert first.result(timeout=15)['status']=='TICKETED'
    assert svc.order('owner',oid)['ticket_numbers']==['ISOLATED-1']
