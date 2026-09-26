"""One isolated operating day: confirmed room/rate facts, real HTTP and ledger.

Synthetic media/guests/money are explicitly fixtures. Unsupported commercial
terms are not hotel confirmations; only confirmation+30min cancellation is used.
"""
from datetime import date, datetime, timedelta, timezone
import sys
import pytest
from sqlalchemy import select
from tests.test_c01_hosted_operating_journey import http
from tests.hosted_review_support import hotel_fixture, prepare_publication, identity, RULES
from go_hotel.services.hosted_direct_booking import ident, now
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.services import hosted_fare_rules as fare
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as desk
from go_hotel.services.hosted_business_day import snapshot, window


@pytest.fixture
def business(monkeypatch,tmp_path):
    h=hotel_fixture(monkeypatch,tmp_path)
    with SessionLocal.begin() as s:
        offer=s.get(m.HostedDirectRoomOfferRow,h['offer']);offer.room_name='摄罗子·圆梦大床房';offer.rate_name='无早餐';offer.price_minor=69800;offer.inventory=50
        pool=s.get(m.HostedDirectInventoryPoolRow,h['pool']);pool.physical_room_key='ROUND_DREAM_KING';pool.physical_room_name=offer.room_name;pool.capacity_total=pool.capacity_available=50
        for d in s.scalars(select(m.HostedInventoryDayRow)):d.capacity_total=d.capacity_available=50
        for d in s.scalars(select(m.HostedRateCalendarDayRow)):d.price_minor=69800
        hotel=s.get(m.HostedDirectHotelRow,h['hotel']);hotel.contact_json={**hotel.contact_json,'phone':'0451-88800808','check_in_after':'14:00','check_out_before':'12:00','operating_clock_policy':{'timezone':'Asia/Shanghai','check_in_after':'14:00','check_out_before':'12:00'},'source_reference':'user-confirmed-2026-08-18-and-2026-09-05','exercise_scope':'FIVE_POOLS_SIX_CONFIRMED_RATES_UNKNOWN_RATES_CLOSED'}
    pools={'ROUND_DREAM_KING':h['pool']}
    with SessionLocal.begin() as s:
        for key,name in [('ROUND_DREAM_TWIN','摄罗子·圆梦双床房'),('PILLOW_MOON_KING','摄罗子·枕月大床房'),('PILLOW_MOON_TWIN','摄罗子·枕月双床房'),('SLEEPING_CLOUD_TWIN','摄罗子·卧云双床房')]:
            pid=ident('pool');pools[key]=pid
            s.add(m.HostedDirectInventoryPoolRow(inventory_pool_id=pid,hosted_hotel_id=h['hotel'],physical_room_key=key,physical_room_name=name,room_details_json={'max_occupancy':3,'occupancy_scope':'ISOLATED_FIXTURE'},capacity_total=50,capacity_available=50,updated_at=now()))
    offer_ids=[h['offer']]
    for key,name in [('ROUND_DREAM_KING','摄罗子·圆梦大床房'),('ROUND_DREAM_TWIN','摄罗子·圆梦双床房')]:
        for breakfast,price in [(0,69800),(1,79800),(2,89800)]:
            if key=='ROUND_DREAM_KING' and breakfast==0:continue
            offer=booking.upsert_offer(h['hotel'],{'room_name':name,'rate_name':str(breakfast)+'早餐','price_minor':price,'inventory':50,'cancellation_policy':'确认后30分钟免费取消；其他条款待确认'},'fixture')['hosted_offer_id'];offer_ids.append(offer)
            with SessionLocal.begin() as s:
                s.add(m.HostedDirectRateVariantRow(rate_variant_id=ident('rate'),inventory_pool_id=pools[key],hosted_offer_id=offer,breakfast_count=breakfast,benefits_json=[],payment_mode='CONTRACT_SIMULATOR',state='ACTIVE'))
    ops.bootstrap_calendar(h['hotel'],{'start_date':h['day'].isoformat(),'end_date':(h['end']+timedelta(days=1)).isoformat()})
    rules={**RULES,'fare_family':'ISOLATED CONFIRMED 30MIN ONLY','cooling_off_anchor':'HOTEL_CONFIRMED'}
    for offer in offer_ids:fare.publish(offer,rules,'isolated://confirmed-30min-other-terms-not-hotel-authority',h['maker'].user_id)
    prepare_publication(h['hotel'],h['maker'],h['checker'],tmp_path,add_rules=False)
    booking.publish(h['hotel'],h['maker'])
    manager,headers=identity('day-manager')
    desk.assign_role(h['hotel'],{'staff_id':manager.user_id,'role':'DUTY_MANAGER','evidence_reference':'isolated://business-day'},h['maker'])
    from zoneinfo import ZoneInfo
    clock={'at':datetime.combine(h['day'],datetime.min.time(),ZoneInfo('Asia/Shanghai')).replace(hour=8).astimezone(timezone.utc)}
    from go_hotel.services.hosted_direct_booking import now as real_now
    def clock_now():return clock['at']
    for name,module in list(sys.modules.items()):
        if name.startswith('go_hotel.services.') and hasattr(module,'now'):
            monkeypatch.setattr(module,'now',clock_now)
    class BusinessDate(date):
        @classmethod
        def today(cls):return h['day']
    monkeypatch.setattr('go_hotel.services.hosted_reservation_operations.date',BusinessDate)
    h.update(manager=manager,manager_headers=headers,clock=clock)
    yield h
    # Lazy imports during the exercise must not retain its clock in later tests.
    for name,module in list(sys.modules.items()):
        if name.startswith('go_hotel.services.') and getattr(module,'now',None) is clock_now:
            module.now=real_now


def post(http,path,headers,body=None,key=None,status=200):
    headers={**headers,**({'Idempotency-Key':key} if key else {})}
    result=http.post(path,headers=headers,**({'json':body} if body is not None else {}))
    assert result.status_code==status,(path,result.text)
    return result.json().get('data',result.json())


def purchase(http,h,key):
    available=post(http,f"/v1/direct/{h['slug']}/availability",{},h['body'])['items']
    available=next(x for x in available if x['hosted_offer_id']==h['offer'])
    body={**h['body'],'expected_fare_rule_hash':available['fare_rule']['rule_hash']}
    r=post(http,f"/v1/direct/{h['slug']}/reservations",h['customer_headers'],body,key)
    assert r['amount_minor']==69800
    assert post(http,f"/v1/direct/{h['slug']}/reservations",h['customer_headers'],body,key)['hosted_reservation_id']==r['hosted_reservation_id']
    aid=post(http,f"/v1/direct/reservations/{r['hosted_reservation_id']}/checkout",h['customer_headers'],{'expected_amount_minor':69800,'currency':'CNY','mode':'CONTRACT_SIMULATOR'})['authorization']['authorization_id']
    post(http,f"/internal/v1/hosted-direct/reservations/{r['hosted_reservation_id']}/decision",h['maker_headers'],{'decision':'CONFIRM'})
    return r['hosted_reservation_id'],aid


def close_day(http,h,day):
    return post(http,f"/internal/v1/hosted-direct/hotels/{h['hotel']}/daily-closes",h['manager_headers'],{'business_date':day})


def test_complete_business_day_with_cancel_refund_difference_repair_and_replay(http,business):
    h=business
    # All business actions use actual routes and real session-backed JWTs.
    rid,aid=purchase(http,h,'fulfilled')
    with SessionLocal() as s:
        movement=s.scalar(select(m.OmnichannelMoneyMovementRow));mid=movement.money_movement_id
    episode=post(http,f'/internal/v1/alipay/authorizations/{aid}/funding-movements/{mid}/unknown-episodes',h['maker_headers'],{'evidence_reference':'isolated://unknown-injection','evidence':{'fixture':True}})
    blocked=close_day(http,h,h['day'].isoformat())
    assert blocked['daily_close_id'] is None and any(x.startswith('PAYMENT_RECONCILIATION_REQUIRED:') for x in blocked['exception_summary_json']['blockers'])
    post(http,f"/internal/v1/alipay/unknown-funding-episodes/{episode['episode_id']}/resolve",h['checker_headers'],{'expected_open_evidence_digest':episode['open_evidence_digest'],'evidence_reference':'isolated://known-simulator-fact','evidence':{'fixture':True}})
    cancelled,_=purchase(http,h,'free-cancel')
    base=f'/v1/direct/reservations/{cancelled}/fare'
    q=post(http,base+'/cancellation-quote',h['customer_headers'])
    assert q['fee_minor']==0
    post(http,base+'/cancel',h['customer_headers'],{'quote_id':q['quote_id'],'expected_fee_minor':0,'currency':'CNY'})
    sid=post(http,f'/internal/v1/stays/reservations/{rid}',h['maker_headers'])['stay_lifecycle_id']
    base=f'/internal/v1/stays/{sid}'
    post(http,base+'/arrive',h['maker_headers'])
    post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://registration'},status=409)
    post(http,base+'/identity-evidence',h['maker_headers'],{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'})
    post(http,base+'/room-assignment',h['maker_headers'],{'room_reference':'ISOLATED-ROUND-DREAM-101'})
    post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://too-early'},status=409)
    h['clock']['at']+=timedelta(hours=6)
    post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://registration'})
    proof={'hotel_fulfillment_evidence':'isolated://folio','guest_checkout_reference':'isolated://guest-checkout','fulfilled_amount_minor':69800}
    post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'},status=409)
    h['clock']['at']+=timedelta(hours=4)
    post(http,base+'/check-out',h['maker_headers'],proof)
    post(http,base+'/settlement-eligibility',h['maker_headers'])
    post(http,f'/internal/v1/alipay/authorizations/{aid}/fulfill',h['maker_headers'],proof)
    first=post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})
    assert post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})==first
    case=post(http,f'/internal/v1/post-stay/stays/{sid}/cases',h['maker_headers'],{'opened_by_party':'GUEST','dispute_type':'SERVICE','assigned_to':'isolated-case-owner','initial_evidence_reference':'isolated://service-issue'})['dispute_case_id']
    day=h['day'].isoformat()
    blocked=close_day(http,h,day)
    assert blocked['daily_close_id'] is None and blocked['exception_summary_json']['state']=='BLOCKED'
    d=post(http,f'/internal/v1/post-stay/cases/{case}/decisions',h['maker_headers'],{'outcome':'PARTIAL_REFUND','refund_amount_minor':9800})['post_stay_decision_id']
    post(http,f'/internal/v1/post-stay/decisions/{d}/approve',h['maker_headers'],{'evidence_reference':'isolated://self-approval'},status=409)
    post(http,f'/internal/v1/post-stay/decisions/{d}/approve',h['checker_headers'],{'evidence_reference':'isolated://independent-refund-decision'})
    e=post(http,f'/internal/v1/post-stay/decisions/{d}/refund-eligibility',h['checker_headers'])['refund_eligibility_id']
    refund=post(http,f'/internal/v1/post-stay/refund-eligibilities/{e}/execute',h['checker_headers'])
    assert post(http,f'/internal/v1/post-stay/refund-eligibilities/{e}/execute',h['checker_headers'])==refund
    post(http,f'/internal/v1/post-stay/cases/{case}/reconcile',h['checker_headers'])
    post(http,f'/internal/v1/post-stay/cases/{case}/close',h['checker_headers'],{'closure_evidence_reference':'isolated://closed'})
    # Inject one missing debit: balanced-looking orders must not hide ledger damage.
    with SessionLocal.begin() as s:
        entry=s.scalar(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.direction=='DEBIT'));entry_id=entry.ledger_entry_id;amount=entry.amount_minor;entry.amount_minor-=1
    broken=close_day(http,h,day)
    assert broken['daily_close_id'] is None
    assert any(x.startswith('MOVEMENT_LEDGER_DIFFERENCE:') for x in broken['exception_summary_json']['blockers'])
    with SessionLocal.begin() as s:s.get(m.OmnichannelLedgerEntryRow,entry_id).amount_minor=amount
    h['clock']['at']=window(day)[1]
    result=close_day(http,h,day);report=result['exception_summary_json'];cny=report['currencies']['CNY']
    assert report['payment_transactions']==report['refund_transactions']==1
    assert (cny['authorization_minor'],cny['capture_minor'],cny['release_minor'],cny['refund_minor'],cny['net_capture_minor'],cny['difference_minor'])==(139600,69800,69800,9800,60000,0)
    assert close_day(http,h,day)==result
    with SessionLocal() as s:
        assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==day))==49
        assert result['inventory_snapshot_json']['total']==250
        assert result['inventory_snapshot_json']['available']==249
        assert s.query(m.HostedDailyCloseRow).count()==1
    # Changes after a successful snapshot must never replay an obsolete success.
    with SessionLocal.begin() as s:s.get(m.OmnichannelLedgerEntryRow,entry_id).amount_minor-=1
    post(http,f"/internal/v1/hosted-direct/hotels/{h['hotel']}/daily-closes",h['manager_headers'],{'business_date':day},status=409)


@pytest.mark.parametrize('bad',['20260901','2026-02-30','bad',123])
def test_business_day_requires_canonical_date(bad):
    with pytest.raises(ValueError,match='VALID_BUSINESS_DATE_REQUIRED'):window(bad)


def test_local_midnight_window():
    start,end=window('2026-09-26')
    assert start.isoformat()=='2026-09-25T16:00:00+00:00'
    assert end-start==timedelta(days=1)


def arrive_and_register(http,h,rid,room):
    sid=post(http,f'/internal/v1/stays/reservations/{rid}',h['maker_headers'])['stay_lifecycle_id']
    base=f'/internal/v1/stays/{sid}'
    post(http,base+'/arrive',h['maker_headers'])
    post(http,base+'/identity-evidence',h['maker_headers'],{'identity_evidence_hash':'b'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'})
    post(http,base+'/room-assignment',h['maker_headers'],{'room_reference':room})
    post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://overnight-registration'})
    return sid


def test_overnight_checkout_next_day_preserves_prior_close_and_opening_balance(http,business):
    h=business;rid,aid=purchase(http,h,'overnight')
    preview=close_day(http,h,h['day'].isoformat())
    assert preview['daily_close_id'] is None and preview['exception_summary_json']['state']=='PREVIEW_OPEN_BUSINESS_DAY'
    h['clock']['at']+=timedelta(hours=6)
    sid=arrive_and_register(http,h,rid,'ISOLATED-OVERNIGHT-102')
    h['clock']['at']=window(h['day'].isoformat())[1]
    first=close_day(http,h,h['day'].isoformat())
    assert first['daily_close_id']
    assert first['exception_summary_json']['currencies']['CNY']['closing_held_minor']==69800
    h['clock']['at']+=timedelta(hours=11)
    proof={'hotel_fulfillment_evidence':'isolated://normal-overnight-folio','guest_checkout_reference':'isolated://normal-11am-checkout','fulfilled_amount_minor':69800}
    post(http,f'/internal/v1/stays/{sid}/check-out',h['maker_headers'],proof)
    post(http,f'/internal/v1/alipay/authorizations/{aid}/fulfill',h['maker_headers'],proof)
    post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})
    assert close_day(http,h,h['day'].isoformat())==first
    next_day=h['end'].isoformat();h['clock']['at']=window(next_day)[1]
    second=close_day(http,h,next_day)
    assert second['daily_close_id']
    balances=second['exception_summary_json']['currencies']['CNY']
    assert (balances['opening_held_minor'],balances['closing_held_minor'],balances['capture_minor'],balances['net_capture_minor'])==(69800,0,69800,69800)
    assert second['inventory_snapshot_json']['total']==second['inventory_snapshot_json']['available']==250


def test_missing_pool_calendar_blocks_whole_day(http,business):
    h=business
    with SessionLocal.begin() as s:
        day=s.scalar(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.stay_date==h['day'].isoformat()));s.delete(day)
    result=close_day(http,h,h['day'].isoformat())
    assert result['daily_close_id'] is None
    assert any(x.startswith('MISSING_INVENTORY_DAY:') for x in result['exception_summary_json']['blockers'])


def test_confirmed_cooling_period_survives_nominal_checkin_boundary():
    from go_hotel.services.hotel_cancellation_clock import terms
    rules={**RULES,'cooling_off_anchor':'HOTEL_CONFIRMED','cancellation_tiers':[{'min_hours':0,'fee_basis_points':10000}]}
    boundary=datetime(2026,9,26,6,tzinfo=timezone.utc)
    result=terms(rules,'2026-09-26',boundary,boundary-timedelta(hours=2),boundary+timedelta(minutes=5),boundary-timedelta(minutes=10))
    assert result['cooling_off_applied'] and result['fee_basis_points']==0


def test_same_hotel_room_cannot_be_assigned_to_two_overlapping_stays(http,business):
    h=business;r1,_=purchase(http,h,'room-a');r2,_=purchase(http,h,'room-b')
    h['clock']['at']+=timedelta(hours=6)
    arrive_and_register(http,h,r1,'SYNTHETIC-201')
    sid=post(http,f'/internal/v1/stays/reservations/{r2}',h['maker_headers'])['stay_lifecycle_id']
    post(http,f'/internal/v1/stays/{sid}/arrive',h['maker_headers'])
    response=post(http,f'/internal/v1/stays/{sid}/room-assignment',h['maker_headers'],{'room_reference':' synthetic-201 '},status=409)
    assert response['detail']=='ROOM_ALREADY_ASSIGNED_FOR_STAY'
