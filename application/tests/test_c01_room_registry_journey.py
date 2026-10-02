"""Real JWT/HTTP room ownership and last-room acceptance on synthetic stock."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from sqlalchemy import select
from tests.test_c01_aoluguya_business_day import http,business,purchase,post
from tests.hosted_review_support import identity
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal


def arrived(http,h,key):
    rid,_=purchase(http,h,key)
    sid=post(http,f'/internal/v1/stays/reservations/{rid}',h['maker_headers'])['stay_lifecycle_id']
    post(http,f'/internal/v1/stays/{sid}/arrive',h['maker_headers'])
    return sid


def test_wrong_pool_room_rejected_without_assignment_or_event(http,business):
    h=business;sid=arrived(http,h,'wrong-pool')
    with SessionLocal.begin() as s:
        other=s.scalar(select(m.HostedDirectInventoryPoolRow).where(
            m.HostedDirectInventoryPoolRow.hosted_hotel_id==h['hotel'],
            m.HostedDirectInventoryPoolRow.inventory_pool_id!=h['pool']))
        other.room_details_json={**other.room_details_json,'room_registry':{
            'version':1,'source_state':'ISOLATED_FIXTURE','source_reference':'isolated://other-pool',
            'rooms':[{'room_reference':'OTHER-POOL-201','state':'ACTIVE'}]}}
        before=s.query(m.GuestStayEventRow).count()
    rejected=post(http,f'/internal/v1/stays/{sid}/room-assignment',h['maker_headers'],
        {'room_reference':'OTHER-POOL-201'},status=409)
    assert rejected['detail']=='ROOM_NOT_IN_RESERVATION_POOL'
    with SessionLocal() as s:
        assert s.get(m.GuestStayLifecycleRow,sid).assigned_room_reference is None
        assert s.query(m.GuestStayEventRow).count()==before


def test_room_registry_revocation_between_assignment_and_checkin_blocks_entry(http,business):
    h=business;sid=arrived(http,h,'revoked-room');base=f'/internal/v1/stays/{sid}'
    post(http,base+'/identity-evidence',h['maker_headers'],
        {'identity_evidence_hash':'c'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'})
    post(http,base+'/room-assignment',h['maker_headers'],{'room_reference':'ISOLATED-ROUND-DREAM-101'})
    with SessionLocal.begin() as s:
        pool=s.get(m.HostedDirectInventoryPoolRow,h['pool']);details=deepcopy(pool.room_details_json)
        details['room_registry']['rooms'][0]['state']='BLOCKED';pool.room_details_json=details
    h['clock']['at']+=timedelta(hours=6)
    rejected=post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://registration'},status=409)
    assert rejected['detail']=='REGISTERED_ROOM_NOT_ACTIVE'
    with SessionLocal() as s:assert s.get(m.GuestStayLifecycleRow,sid).state=='ARRIVED'


def test_fifty_room_pool_is_consumed_by_orders_before_cross_rate_last_room_race(http,business):
    h=business
    available=post(http,f"/v1/direct/{h['slug']}/availability",{},h['body'])['items']
    with SessionLocal() as s:
        offer_ids=set(s.scalars(select(m.HostedDirectRateVariantRow.hosted_offer_id).where(
            m.HostedDirectRateVariantRow.inventory_pool_id==h['pool'])))
    offers=[item for item in available if item['hosted_offer_id'] in offer_ids]
    assert len(offers)==3
    def body(item):return {**h['body'],'hosted_offer_id':item['hosted_offer_id'],
                          'expected_fare_rule_hash':item['fare_rule']['rule_hash']}
    for index in range(49):
        post(http,f"/v1/direct/{h['slug']}/reservations",h['customer_headers'],body(offers[index%3]),f'consume-{index}')
    with SessionLocal() as s:
        assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(
            m.HostedInventoryDayRow.inventory_pool_id==h['pool'],
            m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==1
    barrier=Barrier(2)
    def last(index):
        barrier.wait(timeout=10)
        return http.post(f"/v1/direct/{h['slug']}/reservations",
            headers={**h['customer_headers'],'Idempotency-Key':f'last-{index}'},json=body(offers[index])).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(last,[0,1]))==[200,409]
    with SessionLocal() as s:
        stocks=list(s.scalars(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.stay_date==h['day'].isoformat())))
        assert {row.capacity_available for row in stocks if row.inventory_pool_id==h['pool']}=={0}
        assert {row.capacity_available for row in stocks if row.inventory_pool_id!=h['pool']}=={50}
        assert s.query(m.HostedDirectReservationRow).count()==50


def test_equivalent_registry_spelling_cannot_assign_an_occupied_room(http,business):
    h=business;first=arrived(http,h,'unicode-first');second=arrived(http,h,'unicode-second')
    original='ISOLATED-ROUND-DREAM-101'
    post(http,f'/internal/v1/stays/{first}/room-assignment',h['maker_headers'],{'room_reference':original})
    equivalent=''.join(chr(ord(c)+0xFEE0) for c in original)
    with SessionLocal.begin() as s:
        pool=s.get(m.HostedDirectInventoryPoolRow,h['pool']);details=deepcopy(pool.room_details_json)
        details['room_registry']['rooms'][0]['room_reference']=equivalent;pool.room_details_json=details
    rejected=post(http,f'/internal/v1/stays/{second}/room-assignment',h['maker_headers'],
        {'room_reference':equivalent},status=409)
    assert rejected['detail']=='ROOM_ALREADY_ASSIGNED_FOR_STAY'


def test_checkin_rechecks_occupancy_of_a_stale_assignment(http,business):
    h=business;first=arrived(http,h,'stale-first');second=arrived(http,h,'stale-second')
    ref='ISOLATED-ROUND-DREAM-101'
    post(http,f'/internal/v1/stays/{first}/room-assignment',h['maker_headers'],{'room_reference':ref})
    post(http,f'/internal/v1/stays/{second}/identity-evidence',h['maker_headers'],
        {'identity_evidence_hash':'d'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'})
    with SessionLocal.begin() as s:s.get(m.GuestStayLifecycleRow,second).assigned_room_reference=ref
    h['clock']['at']+=timedelta(hours=6)
    rejected=post(http,f'/internal/v1/stays/{second}/check-in',h['maker_headers'],
        {'registration_evidence_reference':'isolated://stale-assignment'},status=409)
    assert rejected['detail']=='ROOM_ALREADY_ASSIGNED_FOR_STAY'


def registry_body(h):
    with SessionLocal() as s:
        current=deepcopy(s.get(m.HostedDirectInventoryPoolRow,h['pool']).room_details_json['room_registry'])
    return {**current,'expected_version':current['version']}


def test_registry_update_is_scoped_versioned_and_explicitly_not_hotel_confirmation(http,business):
    h=business;path=f"/internal/v1/hosted-direct/inventory-pools/{h['pool']}/room-registry";body=registry_body(h)
    before=body['version']
    readonly,reader_headers=identity('registry-reader',['GO_READ_ONLY'])
    unscoped,unscoped_headers=identity('registry-outsider')
    for headers in [reader_headers,unscoped_headers,h['customer_headers']]:
        assert http.put(path,headers=headers,json=body).status_code==403
    response=http.put(path,headers=h['maker_headers'],json=body)
    assert response.status_code==200,response.text
    result=response.json()['data'];assert result['registry']['version']==before+1 and result['real_hotel_confirmation'] is False
    stale=http.put(path,headers=h['maker_headers'],json=body)
    assert stale.status_code==409 and stale.json()['detail']=='ROOM_REGISTRY_VERSION_CONFLICT'
    with SessionLocal() as s:
        assert s.query(m.AuditEventRow).filter_by(action='HOSTED_ISOLATED_ROOM_REGISTRY_UPDATED').count()==1


def test_registry_cannot_promote_fixture_to_real_confirmation_or_remove_occupied_room(http,business):
    h=business;sid=arrived(http,h,'registry-occupied');ref='ISOLATED-ROUND-DREAM-101'
    post(http,f'/internal/v1/stays/{sid}/room-assignment',h['maker_headers'],{'room_reference':ref})
    path=f"/internal/v1/hosted-direct/inventory-pools/{h['pool']}/room-registry";body=registry_body(h)
    response=http.put(path,headers=h['maker_headers'],json={**body,'source_state':'HOTEL_CONFIRMED'})
    assert response.status_code==409 and response.json()['detail']=='REAL_ROOM_REGISTRY_AUTHORITY_UNVERIFIED'
    body['rooms']=[row for row in body['rooms'] if row['room_reference']!=ref]
    response=http.put(path,headers=h['maker_headers'],json=body)
    assert response.status_code==409 and response.json()['detail']=='ROOM_REGISTRY_ACTIVE_STAY_CONFLICT'


def test_concurrent_registry_updates_use_one_version_and_one_audit(http,business):
    h=business;path=f"/internal/v1/hosted-direct/inventory-pools/{h['pool']}/room-registry";body=registry_body(h)
    barrier=Barrier(2)
    def update(index):
        barrier.wait(timeout=10)
        return http.put(path,headers=h['maker_headers'],json={**body,'source_reference':f'isolated://update-{index}'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(update,[0,1]))==[200,409]
    with SessionLocal() as s:
        assert s.get(m.HostedDirectInventoryPoolRow,h['pool']).room_details_json['room_registry']['version']==body['version']+1
        assert s.query(m.AuditEventRow).filter_by(action='HOSTED_ISOLATED_ROOM_REGISTRY_UPDATED').count()==1
