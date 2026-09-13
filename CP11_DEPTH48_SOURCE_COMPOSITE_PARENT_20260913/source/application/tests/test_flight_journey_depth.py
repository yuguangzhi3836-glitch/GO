"""Behavioral regressions for the recovered R2 reference journey revision."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select, func

from go_hotel.core.config import settings
from go_hotel.db.models import FlightOfferRow, FlightOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.flight.service import now
from tests.test_sprint3a_flight import auth
from tests.vertical_transaction_helpers import confirm_existing_fulfillment


def day(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def criteria(kind='ROUND_TRIP'):
    legs=[{'origin':'PVG','destination':'NRT','departure_date':day(10)},
          {'origin':'NRT','destination':'PVG','departure_date':day(14)}]
    if kind=='ONE_WAY': legs=legs[:1]
    if kind=='MULTI_CITY':
        legs[1]['destination']='SIN'
        legs.append({'origin':'SIN','destination':'PVG','departure_date':day(18)})
    return {'trip_type':kind,'legs':legs}


def search(client, kind='ROUND_TRIP'):
    response=client.post('/v1/flights/journeys/search',json=criteria(kind))
    assert response.status_code==200,response.text
    return response.json()['data']


def compose(client,result,choices=None):
    choices=choices or [0]*len(result['legs'])
    return client.post('/v1/flights/journeys/compose',json={
        'trip_type':result['trip_type'],
        'offer_ids':[leg['items'][choice]['offer_id'] for leg,choice in zip(result['legs'],choices)]})


def order(client,offer,h):
    pb=client.post(f"/v1/flights/offers/{offer['offer_id']}/prebook")
    assert pb.status_code==200,pb.text
    created=client.post('/v1/flights/orders',headers=h,json={
        'prebook_id':pb.json()['data']['prebook_id'],
        'passengers':[{'full_name':'TEST PASSENGER','type':'ADT'}]})
    assert created.status_code==200,created.text
    return created.json()['data']


def ticket(client,offer,h):
    created=order(client,offer,h);oid=created['order_id']
    checkout=client.post(f'/v1/flights/orders/{oid}/checkout',headers=h,json={'payment_method_id':'pm_test_token'})
    assert checkout.status_code==200,checkout.text
    assert checkout.json()['data']['status']=='PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
    confirm_existing_fulfillment(client,oid,'TESTPNR',['TEST-TICKET'])
    return oid


@pytest.mark.parametrize('kind,count',[('ONE_WAY',1),('ROUND_TRIP',2),('MULTI_CITY',3)])
def test_search_selection_prebook_and_order_preserve_entire_journey(client,kind,count):
    result=search(client,kind);assert result['data_mode']=='SIMULATION'
    choices=list(range(count));selected=[leg['items'][i] for i,leg in enumerate(result['legs'])]
    response=compose(client,result,choices);assert response.status_code==200,response.text
    offer=response.json()['data']
    assert len(offer['segments'])==count
    assert offer['total_amount_minor']==sum(x['total_amount_minor'] for x in selected)
    assert offer['tax_amount_minor']==sum(x['tax_amount_minor'] for x in selected)
    assert [s['source_offer_id'] for s in offer['segments']]==[x['offer_id'] for x in selected]
    assert [s['baggage'] for s in offer['segments']]==[x['baggage'] for x in selected]
    h=auth(client);created=order(client,offer,h)
    detail=client.get(f"/v1/flights/orders/{created['order_id']}",headers=h).json()['data']
    assert detail['itinerary']==offer['segments']
    assert detail['total_amount_minor']==offer['total_amount_minor']
    assert detail['trip_type']==kind
    assert detail['status']=='PAYMENT_PENDING' and not detail['ticket_numbers']


@pytest.mark.parametrize('case',['same_airport','reverse_date','same_day','wrong_return','missing_leg','too_many','past','extra_price','unknown_kind'])
def test_invalid_journey_rejected_without_writing_quotes(client,case):
    body=criteria()
    if case=='same_airport':body['legs'][0]['destination']='PVG'
    elif case=='reverse_date':body['legs'][1]['departure_date']=day(9)
    elif case=='same_day':body['legs'][1]['departure_date']=day(10)
    elif case=='wrong_return':body['legs'][1]['destination']='SIN'
    elif case=='missing_leg':body['legs'].pop()
    elif case=='too_many':body['trip_type']='MULTI_CITY';body['legs']*=4
    elif case=='past':body['legs'][0]['departure_date']=day(-1)
    elif case=='extra_price':body['total_amount_minor']=1
    elif case=='unknown_kind':body['trip_type']='RETURN'
    with SessionLocal() as s:before=s.scalar(select(func.count()).select_from(FlightOfferRow))
    assert client.post('/v1/flights/journeys/search',json=body).status_code==422
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(FlightOfferRow))==before


def test_open_jaw_and_six_leg_search_supported(client):
    body={'trip_type':'MULTI_CITY','legs':[{'origin':a,'destination':b,'departure_date':day(2+i*2)} for i,(a,b) in enumerate([('PVG','NRT'),('HND','SIN'),('SIN','BKK'),('BKK','HKG'),('HKG','PEK'),('PEK','PVG')])]}
    r=client.post('/v1/flights/journeys/search',json=body);assert r.status_code==200,r.text
    offer=compose(client,r.json()['data']);assert offer.status_code==200,offer.text
    assert len(offer.json()['data']['segments'])==6


@pytest.mark.parametrize('case',['duplicate','expired','currency','missing','nested','route'])
def test_compose_rejects_unusable_or_mismatched_quotes(client,case):
    result=search(client);ids=[x['items'][0]['offer_id'] for x in result['legs']]
    if case=='duplicate':ids[1]=ids[0]
    elif case=='missing':ids[1]='does-not-exist'
    elif case=='nested':ids[0]=compose(client,search(client,'ONE_WAY')).json()['data']['offer_id']
    else:
        with SessionLocal.begin() as s:
            row=s.get(FlightOfferRow,ids[1])
            if case=='expired':row.expires_at=now()-timedelta(seconds=1)
            elif case=='currency':row.currency='USD'
            elif case=='route':row.destination='SIN'
    r=client.post('/v1/flights/journeys/compose',json={'trip_type':'ROUND_TRIP','offer_ids':ids})
    assert r.status_code==422,r.text


def test_no_silent_return_fields_on_legacy_single_leg_search(client):
    r=client.post('/v1/flights/search',json={'origin':'PVG','destination':'NRT','departure_date':day(5),'return_date':day(10)})
    assert r.status_code==422


def test_round_trip_refund_uses_selected_leg_rules(client):
    h=auth(client);offer=compose(client,search(client),[0,1]).json()['data'];oid=ticket(client,offer,h)
    quote=client.get(f'/v1/flights/orders/{oid}/refund-quote',headers=h)
    assert quote.status_code==200,quote.text
    data=quote.json()['data'];assert data['refund_fee_minor']==55000
    assert data['refund_amount_minor']==offer['total_amount_minor']-55000
    refund=client.post(f'/v1/flights/orders/{oid}/refund',headers=h)
    assert refund.status_code==200,refund.text
    detail=client.get(f'/v1/flights/orders/{oid}',headers=h).json()['data']
    assert detail['status']=='REFUNDED' and len(detail['itinerary'])==2


def test_nonrefundable_leg_cannot_be_refunded_and_multi_change_is_not_silently_first_leg(client):
    h=auth(client);offer=compose(client,search(client),[0,2]).json()['data'];oid=ticket(client,offer,h)
    assert client.get(f'/v1/flights/orders/{oid}/refund-quote',headers=h).status_code==422
    assert client.post(f'/v1/flights/orders/{oid}/refund',headers=h).status_code==422
    r=client.post(f'/v1/flights/orders/{oid}/change-quote',headers=h,json={'new_departure_date':day(12)})
    assert r.status_code==409 and 'FLIGHT_CHANGE_SEGMENT_SELECTION_REQUIRED' in r.text
    detail=client.get(f'/v1/flights/orders/{oid}',headers=h).json()['data']
    assert detail['status']=='TICKETED' and detail['itinerary']==offer['segments']


def test_wrong_passenger_count_rejected_before_order_creation(client):
    h=auth(client);offer=compose(client,search(client)).json()['data']
    pb=client.post(f"/v1/flights/offers/{offer['offer_id']}/prebook").json()['data']
    r=client.post('/v1/flights/orders',headers=h,json={'prebook_id':pb['prebook_id'],'passengers':[{'full_name':'TEST ONE','type':'ADT'},{'full_name':'TEST TWO','type':'ADT'}]})
    assert r.status_code==422,r.text
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(FlightOrderRow))==0


def test_new_journey_paths_do_not_enable_production_fixtures(client,monkeypatch):
    from go_hotel.flight.journeys import JourneySearch, JourneyCompose, search_journey, compose_journey
    monkeypatch.setattr(settings,'app_env','production')
    with pytest.raises(ValueError,match='FLIGHT_PROVIDER_TRUTH_REQUIRED:JOURNEY_SEARCH'):
        search_journey(JourneySearch(**criteria()))
    with pytest.raises(ValueError,match='FLIGHT_PROVIDER_TRUTH_REQUIRED:JOURNEY_COMPOSE'):
        compose_journey(JourneyCompose(trip_type='ONE_WAY',offer_ids=['test']))


def test_prebook_cannot_outlive_shortest_selected_quote(client):
    result=search(client)
    with SessionLocal.begin() as s:
        short=s.get(FlightOfferRow,result['legs'][1]['items'][0]['offer_id'])
        short.expires_at=now()+timedelta(minutes=2)
        expires=short.expires_at
    offer=compose(client,result).json()['data']
    pb=client.post(f"/v1/flights/offers/{offer['offer_id']}/prebook")
    assert pb.status_code==200,pb.text
    assert pb.json()['data']['expires_at']==expires.isoformat()
