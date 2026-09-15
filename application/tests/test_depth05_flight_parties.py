from datetime import date,timedelta
import pytest
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (FlightOfferRow,FlightOrderRow,FlightRefundRow,
    OmnichannelMoneyMovementRow as Movement,PaymentOrderRootRow as Root)
from go_hotel.flight.service import FlightService,flight_service
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault
from tests.test_flight_journey_depth import criteria
from tests.test_sprint3a_flight import auth


def offer(client,count=2,kind='ROUND_TRIP'):
    searched=client.post('/v1/flights/journeys/search',json={**criteria(kind),'adults':count})
    assert searched.status_code==200,searched.text
    data=searched.json()['data'];assert data['passenger_count']==count
    composed=client.post('/v1/flights/journeys/compose',json={'trip_type':kind,'offer_ids':[leg['items'][0]['offer_id'] for leg in data['legs']]})
    assert composed.status_code==200,composed.text
    return composed.json()['data']


def create(client,headers,count=2,kind='ROUND_TRIP',traveler_ids=None):
    quoted=offer(client,count,kind)
    pb=client.post(f"/v1/flights/offers/{quoted['offer_id']}/prebook").json()['data']
    assert pb['passenger_count']==count
    body={'prebook_id':pb['prebook_id'],'traveler_ids':traveler_ids} if traveler_ids else {
        'prebook_id':pb['prebook_id'],'passengers':[{'full_name':f'PERSON {i}','type':'ADT'} for i in range(count)]}
    r=client.post('/v1/flights/orders',headers=headers,json=body)
    assert r.status_code==200,r.text
    return r.json()['data'],quoted


def pay(client,headers,order):
    path=f"/v1/consumer/checkout/FLIGHT/{order['order_id']}"
    body={'mode':'CONTRACT_SIMULATOR','currency':'CNY','expected_amount_minor':order['total_amount_minor']}
    bad=client.post(path,headers={**headers,'Idempotency-Key':'underpay'},json={**body,'expected_amount_minor':1})
    assert bad.status_code==409
    for key in ['first-payment','retry-another-device']:
        response=client.post(path,headers={**headers,'Idempotency-Key':key},json=body)
        assert response.status_code==200,response.text
    return client.get(f"/v1/flights/orders/{order['order_id']}",headers=headers).json()['data']


@pytest.mark.parametrize('kind,legs',[('ONE_WAY',1),('ROUND_TRIP',2),('MULTI_CITY',3)])
def test_three_adults_have_matching_prices_tickets_and_original_refund(client,kind,legs):
    headers=auth(client);order,quoted=create(client,headers,3,kind)
    assert order['total_amount_minor']==468000*3*legs
    assert quoted['tax_amount_minor']==68000*3*legs
    assert quoted['refund_policy']['fee_minor']==20000*3*legs
    ticketed=pay(client,headers,order)
    assert len(ticketed['ticket_numbers'])==len(set(ticketed['ticket_numbers']))==3*legs
    assert {(x['leg_index'],x['passenger_index']) for x in ticketed['ticket_assignments']}=={(l,p) for l in range(legs) for p in range(3)}
    path=f"/v1/flights/orders/{order['order_id']}"
    quote=client.get(path+'/refund-quote',headers=headers).json()['data']
    assert quote['refund_amount_minor']==(468000-20000)*3*legs
    first=client.post(path+'/refund',headers={**headers,'Idempotency-Key':'refund-first'})
    assert first.status_code==200,first.text
    repeated=client.post(path+'/refund',headers={**headers,'Idempotency-Key':'refund-retry'})
    assert repeated.status_code==200,repeated.text
    assert repeated.json()['data']['refund_id']==first.json()['data']['refund_id']
    with SessionLocal() as s:
        root=s.scalar(select(Root).where(Root.business_type=='FLIGHT_ORDER',Root.business_id==order['order_id']))
        movements=s.scalars(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id)).all()
        captures=[m for m in movements if m.movement_type=='CAPTURE'];refunds=[m for m in movements if m.movement_type=='REFUND']
        assert len(captures)==len(refunds)==1
        assert refunds[0].parent_movement_id==captures[0].money_movement_id
        assert refunds[0].amount_minor==quote['refund_amount_minor']


@pytest.mark.parametrize('count',[0,10,True,'2',1.5])
def test_bad_party_counts_rejected_before_quotes_are_written(client,count):
    assert client.post('/v1/flights/journeys/search',json={**criteria(),'adults':count}).status_code==422
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(FlightOfferRow))==0


def test_composition_rejects_different_party_sizes(client):
    first=client.post('/v1/flights/journeys/search',json={**criteria(),'adults':2}).json()['data']
    second=client.post('/v1/flights/journeys/search',json={**criteria(),'adults':3}).json()['data']
    response=client.post('/v1/flights/journeys/compose',json={'trip_type':'ROUND_TRIP','offer_ids':[first['legs'][0]['items'][0]['offer_id'],second['legs'][1]['items'][0]['offer_id']]})
    assert response.status_code==422 and 'PASSENGER_COUNT_MISMATCH' in response.text


@pytest.mark.parametrize('passengers',[[],[{'full_name':'','type':'ADT'}],[{'full_name':'CHILD','type':'CHD'}]])
def test_missing_phantom_and_unsupported_passengers_never_create_order(client,passengers):
    headers=auth(client);quoted=offer(client,1,'ONE_WAY')
    pb=client.post(f"/v1/flights/offers/{quoted['offer_id']}/prebook").json()['data']
    response=client.post('/v1/flights/orders',headers=headers,json={'prebook_id':pb['prebook_id'],'passengers':passengers})
    assert response.status_code==422,response.text
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(FlightOrderRow))==0


def test_nine_adult_boundary_and_server_count_cannot_be_changed_at_order_time(client):
    headers=auth(client);quoted=offer(client,9,'ONE_WAY')
    assert quoted['total_amount_minor']==468000*9
    pb=client.post(f"/v1/flights/offers/{quoted['offer_id']}/prebook").json()['data']
    response=client.post('/v1/flights/orders',headers=headers,json={'prebook_id':pb['prebook_id'],'passengers':[{'full_name':'ONLY ONE','type':'ADT'}]})
    assert response.status_code==422 and 'REQUOTE_REQUIRED' in response.text


def test_vault_party_rejects_duplicate_and_revoked_travelers(client):
    r=client.post('/v1/consumer/auth/register',json={'email':'party@example.test','password':'StrongPass123!','display_name':'NICKNAME'})
    uid=r.json()['data']['profile']['user_id']
    token=client.post('/v1/mobile/auth/login',json={'email':'party@example.test','password':'StrongPass123!'}).json()['data']['access_token']
    client.cookies.clear();headers={'Authorization':'Bearer '+token};ids=[]
    for i in range(2):
        job=vault.create_import(uid,{'source_type':'MANUAL','items':[{'entity_type':'TRAVELER','value':{'full_name':f'REAL PERSON {i}','relationship_type':'SELF' if i==0 else 'FAMILY'}}]})
        vault.review_item(uid,job['import_job_id'],job['items'][0]['import_item_id'],'ACCEPT')
        ids.append(vault.commit_import(uid,job['import_job_id'])['items'][0]['resolution_traveler_id'])
    quoted=offer(client,2)
    pb=client.post(f"/v1/flights/offers/{quoted['offer_id']}/prebook").json()['data']
    duplicate=client.post('/v1/flights/orders',headers=headers,json={'prebook_id':pb['prebook_id'],'traveler_ids':[ids[0],ids[0]]})
    assert duplicate.status_code==409 and 'DUPLICATE' in duplicate.text
    vault.set_permission(uid,ids[1],'USE_FOR_BOOKING',False)
    denied=client.post('/v1/flights/orders',headers=headers,json={'prebook_id':pb['prebook_id'],'traveler_ids':ids})
    assert denied.status_code==409 and 'PERMISSION_REQUIRED' in denied.text
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(FlightOrderRow))==0
    vault.set_permission(uid,ids[1],'USE_FOR_BOOKING',True)
    accepted=client.post('/v1/flights/orders',headers=headers,json={'prebook_id':pb['prebook_id'],'traveler_ids':ids})
    assert accepted.status_code==200,accepted.text
    assert [p['full_name'] for p in accepted.json()['data']['passengers']]==['REAL PERSON 0','REAL PERSON 1']


def test_change_surcharge_refund_survives_partial_failure_and_process_restart(client,monkeypatch):
    headers=auth(client);order,quoted=create(client,headers,2,'ONE_WAY');pay(client,headers,order)
    oid=order['order_id'];uid=order['account_id']
    quote=flight_service.change_quote(uid,oid,(date.today()+timedelta(days=12)).isoformat())
    assert quote['fare_difference_minor']==60000 and quote['change_fee_minor']==20000
    flight_service.execute_change(uid,oid,quote['quote_id'])
    changed=flight_service.admin_external_state(oid,'TICKETED','isolated-change-confirmed','isolated-operator','SIM-NEW',['SIM-T1','SIM-T2'])
    assert changed['total_amount_minor']==order['total_amount_minor']+80000
    original=money.create;refund_attempts=0
    def interrupted(intent,body,key,actor):
        nonlocal refund_attempts
        if body['movement_type']=='REFUND':
            refund_attempts+=1
            if refund_attempts==2:raise ValueError('ISOLATED_TEMPORARY_REFUND_INTERRUPTION')
        return original(intent,body,key,actor)
    monkeypatch.setattr(money,'create',interrupted)
    with pytest.raises(ValueError,match='ISOLATED_TEMPORARY'):flight_service.refund(uid,oid)
    with SessionLocal() as s:
        assert s.get(FlightOrderRow,oid).status=='REFUND_PENDING'
        assert s.scalar(select(FlightRefundRow).where(FlightRefundRow.order_id==oid)).status=='REFUND_PENDING'
        assert len(s.scalars(select(Movement).where(Movement.movement_type=='REFUND',Movement.state=='CONFIRMED')).all())==1
    with pytest.raises(ValueError,match='NOT_CHANGEABLE'):flight_service.change_quote(uid,oid,'2030-01-01')
    recovered=FlightService().refund(uid,oid)
    assert recovered['status']=='REFUND_COMPLETED'
    assert recovered['refund_amount_minor']==changed['total_amount_minor']-40000
    with SessionLocal() as s:
        refunds=s.scalars(select(Movement).where(Movement.movement_type=='REFUND')).all()
        assert len(refunds)==2 and sum(r.amount_minor for r in refunds)==recovered['refund_amount_minor']
        assert len({r.root_payment_intent_id for r in refunds})==2
        for refund in refunds:
            assert s.get(Movement,refund.parent_movement_id).movement_type=='CAPTURE'
    assert FlightService().refund(uid,oid)['refund_id']==recovered['refund_id']


def test_change_authorization_failure_preserves_claim_and_can_resume(client,monkeypatch):
    from go_hotel.services.vertical_money_bridge import vertical_money_bridge as bridge
    headers=auth(client);order,_=create(client,headers,2,'ONE_WAY');pay(client,headers,order)
    uid=order['account_id'];oid=order['order_id'];day=(date.today()+timedelta(days=12)).isoformat()
    first=flight_service.change_quote(uid,oid,day);second=flight_service.change_quote(uid,oid,day)
    original=bridge.prepare_adjustment
    def fail(*args,**kwargs):raise ValueError('ISOLATED_AUTHORIZATION_TIMEOUT')
    monkeypatch.setattr(bridge,'prepare_adjustment',fail)
    with pytest.raises(ValueError,match='AUTHORIZATION_TIMEOUT'):flight_service.execute_change(uid,oid,first['quote_id'])
    with pytest.raises(ValueError,match='NOT_REFUNDABLE'):flight_service.refund(uid,oid)
    with pytest.raises(ValueError,match='QUOTE_INVALID'):flight_service.execute_change(uid,oid,second['quote_id'])
    monkeypatch.setattr(bridge,'prepare_adjustment',original)
    resumed=FlightService().execute_change(uid,oid,first['quote_id'])
    assert resumed['status']=='UNKNOWN_EXTERNAL_STATE'
    assert FlightService().execute_change(uid,oid,first['quote_id'])['idempotent_replay']
    with SessionLocal() as s:
        roots=s.scalars(select(Root).where(Root.business_type=='FLIGHT_CHANGE')).all()
        assert len(roots)==1
        auths=s.scalars(select(Movement).where(Movement.root_payment_intent_id==roots[0].payment_intent_id,
            Movement.movement_type=='AUTHORIZATION')).all()
        assert len(auths)==1


def test_simultaneous_flight_refund_requests_return_one_durable_refund(client):
    from concurrent.futures import ThreadPoolExecutor
    headers=auth(client);order,_=create(client,headers,2);pay(client,headers,order)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:FlightService().refund(order['account_id'],order['order_id']),range(2)))
    assert results[0]['refund_id']==results[1]['refund_id']
    with SessionLocal() as s:
        assert len(s.scalars(select(FlightRefundRow).where(FlightRefundRow.order_id==order['order_id'])).all())==1
        assert len(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')).all())==1
