"""Database-backed ownership checks; all room registrations are synthetic."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from go_hotel.db.models import (HostedDirectHotelRow as Hotel, HostedDirectInventoryPoolRow as Pool,
    HostedDirectRateVariantRow as Variant, HostedReservationNightRow as Night, HostedInventoryDayRow as Day)
from go_hotel.services.hosted_room_registry import validate_room
from go_hotel.services.payment_sandbox_cutover import now
from tests.test_payment_sandbox_audit_integrity import audit

pytestmark = pytest.mark.no_db


@pytest.fixture
def rooms(audit):
    _, sessions, _ = audit
    for model in (Pool, Variant, Night, Day):
        model.__table__.create(sessions.kw['bind'])
    registry={'version':1,'source_state':'ISOLATED_FIXTURE','source_reference':'isolated://registry',
              'rooms':[{'room_reference':'ROOM-101','state':'ACTIVE'}]}
    with sessions.begin() as s:
        s.get(Hotel,'isolated-hotel').contact_json={'inventory_data_mode':'SIMULATION'}
        for pid,ref in [('pool-a','ROOM-101'),('pool-b','ROOM-201')]:
            r=deepcopy(registry);r['rooms'][0]['room_reference']=ref
            s.add(Pool(inventory_pool_id=pid,hosted_hotel_id='isolated-hotel',physical_room_key=pid,
                physical_room_name=pid,room_details_json={'room_registry':r},capacity_total=50,capacity_available=50,updated_at=now()))
        s.add(Variant(rate_variant_id='rate',inventory_pool_id='pool-a',hosted_offer_id='offer',
            breakfast_count=0,benefits_json=[],payment_mode='CONTRACT_SIMULATOR',state='ACTIVE'))
    return sessions, SimpleNamespace(hosted_offer_id='offer',hosted_reservation_id='reservation')


def check(rooms,ref='ROOM-101'):
    sessions,reservation=rooms
    with sessions() as s:return validate_room(s,reservation,s.get(Hotel,'isolated-hotel'),ref)


def test_registered_room_preserves_canonical_identity_and_binding(rooms):
    result=check(rooms,' room-101 ')
    assert result['room_reference']=='ROOM-101' and result['inventory_pool_id']=='pool-a'
    assert result['room_registry_source_state']=='ISOLATED_FIXTURE' and len(result['room_registry_hash'])==64


@pytest.mark.parametrize('reference,error',[('ROOM-201','ROOM_NOT_IN_RESERVATION_POOL'),
    ('UNKNOWN','ROOM_NOT_REGISTERED_FOR_HOTEL'),('', 'VALID_REGISTERED_ROOM_REFERENCE'),
    ('x'*129,'VALID_REGISTERED_ROOM_REFERENCE')])
def test_unowned_or_invalid_room_rejected(rooms,reference,error):
    with pytest.raises(ValueError,match=error):check(rooms,reference)


@pytest.mark.parametrize('damage,error',[
    ('missing','ROOM_REGISTRY_REQUIRED'),('inactive','REGISTERED_ROOM_NOT_ACTIVE'),
    ('duplicate','DUPLICATE_REGISTERED_ROOM_REFERENCE'),('ambiguous','AMBIGUOUS_ROOM_POOL_BINDING'),
    ('cross_hotel','ROOM_OFFER_HOTEL_POOL_MISMATCH'),('no_variant','ROOM_OFFER_POOL_BINDING_REQUIRED'),
    ('simulation_as_live','SIMULATED_ROOM_REGISTRY_NOT_LIVE_AUTHORITY'),
    ('moved_pool','ROOM_POOL_RESERVATION_NIGHT_MISMATCH'),
])
def test_registry_corruption_and_binding_changes_fail_closed(rooms,damage,error):
    sessions,reservation=rooms
    with sessions.begin() as s:
        pool=s.get(Pool,'pool-a');details=deepcopy(pool.room_details_json)
        if damage=='missing':details={}
        elif damage=='inactive':details['room_registry']['rooms'][0]['state']='BLOCKED'
        elif damage=='duplicate':details['room_registry']['rooms'].append({'room_reference':' room-101 ','state':'ACTIVE'})
        elif damage=='ambiguous':
            other=s.get(Pool,'pool-b');d=deepcopy(other.room_details_json)
            d['room_registry']['rooms'][0]['room_reference']='ROOM-101';other.room_details_json=d
        elif damage=='cross_hotel':pool.hosted_hotel_id='other-hotel'
        elif damage=='no_variant':s.delete(s.get(Variant,'rate'))
        elif damage=='simulation_as_live':s.get(Hotel,'isolated-hotel').contact_json={}
        elif damage=='moved_pool':
            s.add(Day(inventory_day_id='day',inventory_pool_id='pool-b',stay_date='2026-09-26',
                capacity_total=50,capacity_available=49,sale_state='OPEN',updated_at=now()))
            s.add(Night(reservation_night_id='night',hosted_reservation_id='reservation',inventory_day_id='day',
                stay_date='2026-09-26',price_minor=69800,state='HELD'))
        pool.room_details_json=details
    with pytest.raises(ValueError,match=error):check(rooms)


def test_closed_rate_does_not_change_existing_room_ownership(rooms):
    sessions,_=rooms
    with sessions.begin() as s:s.get(Variant,'rate').state='INACTIVE'
    assert check(rooms)['inventory_pool_id']=='pool-a'
