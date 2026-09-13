"""Multi-leg change, exact consent, durable money decision and coupon ownership."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (FlightOrderRow as Order, FlightChangePlanRow as Plan,
    FlightChangeQuoteRow as Quote, FlightChangeResolutionRow as Resolution,
    OmnichannelMoneyMovementRow as Movement)
from go_hotel.flight.service import flight_service as flights
from go_hotel.services import flight_change_resolution as recovery
from tests.test_depth05_flight_parties import auth, create, pay
from tests.test_flight_journey_depth import day


def booked(client, kind='ROUND_TRIP', party=2):
    h=auth(client);o,_=create(client,h,party,kind);o=pay(client,h,o)
    with SessionLocal() as s:owner=s.get(Order,o['order_id']).account_id
    return owner,o,h


def consent(q):
    return {'quote_hash':q['quote_hash'],'expected_total_due_minor':q['total_due_minor'],
            'currency':q['currency'],'confirmed':True}


def pending(client, kind='ROUND_TRIP', changes=None):
    owner,o,h=booked(client,kind)
    q=flights.change_quote(owner,o['order_id'],changes=changes or [{'leg_index':0,'new_departure_date':day(12)}])
    flights.execute_change(owner,o['order_id'],q['quote_id'],consent(q))
    return owner,o,q,h


def resolve(o,q,state='TICKETED',tickets=None,reference='isolated://flight-change'):
    return flights.admin_external_state(o['order_id'],state,reference,'ops',
        'NEWPNR' if state=='TICKETED' else None,
        tickets if tickets is not None else [f'NEW-{i}' for i in range(2*len(q['changes']))] if state=='TICKETED' else [],q['quote_id'])


def amounts():
    with SessionLocal() as s:
        return {kind:sum(m.amount_minor for m in s.scalars(select(Movement).where(Movement.movement_type==kind,Movement.state=='CONFIRMED'))) for kind in ['CAPTURE','REFUND','RELEASE']}


@pytest.mark.parametrize('kind,changes', [
    ('ROUND_TRIP',[{'leg_index':0,'new_departure_date':day(12)}]),
    ('ROUND_TRIP',[{'leg_index':1,'new_departure_date':day(16)}]),
    ('MULTI_CITY',[{'leg_index':1,'new_departure_date':day(16)}]),
    ('MULTI_CITY',[{'leg_index':0,'new_departure_date':day(11)},{'leg_index':2,'new_departure_date':day(20)}]),
])
def test_selected_legs_replace_only_their_passenger_tickets_then_refund(client,kind,changes):
    owner,o,q,h=pending(client,kind,changes)
    assert q['total_due_minor']==80000*len(changes)
    changed=resolve(o,q)
    assert resolve(o,q)==changed
    selected={x['leg_index'] for x in changes}
    for index,leg in enumerate(changed['itinerary']):
        if index not in selected:
            assert leg==o['itinerary'][index]
            assert changed['ticket_numbers'][index*2:index*2+2]==o['ticket_numbers'][index*2:index*2+2]
        else:
            target=next(x for x in changes if x['leg_index']==index)
            assert leg['departure_date']==target['new_departure_date']
            assert leg['supplier_reference']=='NEWPNR'
    assert len(changed['ticket_assignments'])==len(o['itinerary'])*2
    assert changed['total_amount_minor']==o['total_amount_minor']+q['total_due_minor']
    refund=flights.refund_quote(owner,o['order_id']);flights.refund(owner,o['order_id'])
    assert amounts()['REFUND']==refund['refund_amount_minor']
    assert amounts()['CAPTURE']==o['total_amount_minor']+q['total_due_minor']
    rows=client.get('/v1/consumer/unified-trips',headers=h).json()['data']['items']
    assert any(x['order_id']==o['order_id'] and x['native_status']=='REFUNDED' for x in rows)


@pytest.mark.parametrize('kind', ['missing','wrong_hash','wrong_amount','currency','false_consent'])
def test_unaccepted_multi_leg_quote_never_authorizes_money(client,kind):
    owner,o,_=booked(client);q=flights.change_quote(owner,o['order_id'],day(12),0)
    accepted=consent(q)
    if kind=='missing':accepted=None
    else:accepted.update({'wrong_hash':{'quote_hash':'f'*64},'wrong_amount':{'expected_total_due_minor':1},'currency':{'currency':'USD'},'false_consent':{'confirmed':False}}[kind])
    before=amounts()
    with pytest.raises(ValueError,match='CONSENT_INVALID'):flights.execute_change(owner,o['order_id'],q['quote_id'],accepted)
    assert amounts()==before and flights.order(owner,o['order_id'])['status']=='TICKETED'


@pytest.mark.parametrize('changes', [
    [{'leg_index':True,'new_departure_date':day(12)}],
    [{'leg_index':2,'new_departure_date':day(12)}],
    [{'leg_index':0,'new_departure_date':'2026-02-30'}],
    [{'leg_index':0,'new_departure_date':day(15)}],
    [{'leg_index':0,'new_departure_date':day(12)},{'leg_index':0,'new_departure_date':day(11)}],
])
def test_invalid_selection_or_date_order_cannot_create_plan(client,changes):
    owner,o,_=booked(client)
    with pytest.raises(ValueError,match='INVALID'):flights.change_quote(owner,o['order_id'],changes=changes)
    with SessionLocal() as s:assert not list(s.scalars(select(Plan)))


def test_changed_order_or_plan_cannot_borrow_prior_consent(client):
    owner,o,_=booked(client);q=flights.change_quote(owner,o['order_id'],day(12),0)
    with SessionLocal.begin() as s:
        p=s.get(Plan,q['quote_id']);data=deepcopy(p.plan_json);data['changes'][0]['leg_index']=1;p.plan_json=data
    with pytest.raises(ValueError,match='INTEGRITY_INVALID'):flights.execute_change(owner,o['order_id'],q['quote_id'],consent(q))
    assert amounts()['CAPTURE']==o['total_amount_minor']


@pytest.mark.parametrize('decision', ['TICKETED','FAILED'])
def test_crash_after_money_recovers_once_and_rejects_opposite_decision(client,monkeypatch,decision):
    owner,o,q,_=pending(client);old_event=recovery._event
    def lost(s,order,kind,*args):
        if kind in {'CHANGE_RECONCILED_TO_TICKETED','CHANGE_FAILED_RESTORED_TICKETED'}:raise RuntimeError('AFTER_MONEY')
        return old_event(s,order,kind,*args)
    monkeypatch.setattr(recovery,'_event',lost)
    with pytest.raises(RuntimeError,match='AFTER_MONEY'):resolve(o,q,decision)
    assert flights.order(owner,o['order_id'])['status']=='UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError,match='CONFLICT'):resolve(o,q,'FAILED' if decision=='TICKETED' else 'TICKETED')
    monkeypatch.setattr(recovery,'_event',old_event)
    result=resolve(o,q,decision);assert resolve(o,q,decision)==result
    assert amounts()['CAPTURE']==o['total_amount_minor']+(q['total_due_minor'] if decision=='TICKETED' else 0)
    assert amounts()['RELEASE']==(q['total_due_minor'] if decision=='FAILED' else 0)
    if decision=='FAILED':assert result['ticket_numbers']==o['ticket_numbers'] and result['itinerary']==o['itinerary']


def test_concurrent_opposite_resolution_cannot_change_money_decision(client,monkeypatch):
    owner,o,q,_=pending(client);entered=Event();finish=Event();original=recovery.vertical_money_bridge.capture_adjustment
    def paused(*args):entered.set();assert finish.wait(10);return original(*args)
    monkeypatch.setattr(recovery.vertical_money_bridge,'capture_adjustment',paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(resolve,o,q)
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError,match='CONFLICT'):resolve(o,q,'FAILED')
        finally:finish.set()
        assert task.result()['status']=='TICKETED'
    assert amounts()['CAPTURE']==o['total_amount_minor']+q['total_due_minor']


def test_wrong_coupon_count_and_foreign_receipt_never_complete_order(client,monkeypatch):
    owner,o,q,_=pending(client)
    with pytest.raises(ValueError,match='TICKETS_INVALID'):resolve(o,q,tickets=['ONLY-ONE'])
    monkeypatch.setattr(recovery.vertical_money_bridge,'capture_adjustment',lambda *a,**k:{'capture_id':'absent'})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):resolve(o,q)
    assert flights.order(owner,o['order_id'])['status']=='UNKNOWN_EXTERNAL_STATE'
    assert amounts()['CAPTURE']==o['total_amount_minor']


def test_old_resolution_replay_cannot_overwrite_next_change(client):
    owner,o,q,_=pending(client);first=resolve(o,q)
    next_quote=flights.change_quote(owner,o['order_id'],day(17),1)
    flights.execute_change(owner,o['order_id'],next_quote['quote_id'],consent(next_quote))
    assert resolve(o,q)==first
    assert flights.order(owner,o['order_id'])['status']=='UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError,match='QUOTE_ID_REQUIRED'):
        flights.admin_external_state(o['order_id'],'TICKETED','isolated://ambiguous','ops','LATE',['LATE1','LATE2'])
    result=resolve(first,next_quote,tickets=['RETURN1','RETURN2'])
    assert result['ticket_numbers'][:2]==first['ticket_numbers'][:2]


def test_http_requires_selection_and_binds_exact_confirmed_quote(client):
    owner,o,h=booked(client);path='/v1/flights/orders/'+o['order_id']
    response=client.post(path+'/change-quote',headers=h,json={'new_departure_date':day(12),'leg_index':0})
    assert response.status_code==200,response.text
    q=response.json()['data']
    assert client.post(path+'/execute-change/'+q['quote_id'],headers=h).status_code==422
    response=client.post(path+'/execute-change/'+q['quote_id'],headers=h,json=consent(q))
    assert response.status_code==200 and response.json()['data']['status']=='UNKNOWN_EXTERNAL_STATE'
