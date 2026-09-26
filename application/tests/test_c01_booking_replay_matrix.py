"""The same order/idempotency contract across the four hosted HTTP entrances."""
from datetime import timedelta
import pytest
from sqlalchemy import select
from tests.test_c01_aoluguya_business_day import http,business,post
from tests.test_c01_money_authority_matrix import facts
from tests.hosted_review_support import identity
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as desk


@pytest.mark.parametrize('entry',['reservations','managed-reservations','phone-reservations','governed-phone-reservations'])
def test_same_booking_key_replays_without_new_nights_events_or_notifications_and_changed_body_fails(http,business,entry):
    h=business;phone='phone' in entry
    staff,staff_headers=identity('phone-reservations',['GO_ORDER_OPS'])
    desk.assign_role(h['hotel'],{'staff_id':staff.user_id,'role':'RESERVATIONS','evidence_reference':'isolated://replay-phone'},h['maker'])
    headers=staff_headers if phone else h['customer_headers']
    path=(f"/internal/v1/hosted-direct/{h['slug']}/" if phone else f"/v1/direct/{h['slug']}/")+entry
    available=post(http,f"/v1/direct/{h['slug']}/availability",{},h['body'])['items']
    item=next(x for x in available if x['hosted_offer_id']==h['offer'])
    body={**h['body'],'expected_fare_rule_hash':item['fare_rule']['rule_hash']}
    key='replay-'+entry
    first=post(http,path,headers,body,key);rid=first['hosted_reservation_id']
    with SessionLocal() as s:
        r=s.get(m.HostedDirectReservationRow,rid);stay=s.get(m.HostedReservationStayRow,rid)
        assert r.hosted_offer_id==h['offer'] and (r.check_in,r.check_out)==(body['check_in'],body['check_out'])
        assert stay.source==('PHONE' if phone else 'GO_PAGE')
        assert stay.created_by==(staff.user_id if phone else h['customer'].user_id)
        nights=list(s.scalars(select(m.HostedReservationNightRow).where(m.HostedReservationNightRow.hosted_reservation_id==rid)))
        assert len(nights)==1 and nights[0].state=='HELD'
        day=s.get(m.HostedInventoryDayRow,nights[0].inventory_day_id)
        assert day.inventory_pool_id==h['pool'] and day.capacity_available==49
        assert s.query(m.HostedDirectReservationRow).count()==1
        assert s.query(m.HostedDirectReservationEventRow).filter_by(hosted_reservation_id=rid).count()==1
        notifications=list(s.scalars(select(m.HostedReservationNotificationRow).where(m.HostedReservationNotificationRow.hosted_reservation_id==rid)))
        assert len(notifications)==2 and {n.delivery_state for n in notifications}=={'QUEUED_NOT_SENT'}
    frozen=facts()
    assert post(http,path,headers,body,key)==first
    assert facts()==frozen
    for changed in [{**body,'guest_name':'DIFFERENT SYNTHETIC GUEST'},
                    {**body,'check_out':(h['end']+timedelta(days=1)).isoformat()}]:
        rejected=post(http,path,headers,changed,key,status=409)
        assert rejected['detail']=='IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST'
        assert facts()==frozen
