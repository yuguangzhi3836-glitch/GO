from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectInventoryPoolRow,HostedDirectRateVariantRow,HostedInventoryDayRow,HostedRateCalendarDayRow,HostedReservationStayRow,HostedReservationNightRow,HostedReservationNotificationRow,HostedDirectReservationEventRow
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.aoluguya_inventory import configure_aoluguya_legacy_fixture as configure_aoluguya
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as svc

def setup():
 booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin');configure_aoluguya()
 with SessionLocal() as s:
  hotel=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug=='aoluguya-harbin'));variant=s.scalar(select(HostedDirectRateVariantRow));offer_id=variant.hosted_offer_id;pool_id=variant.inventory_pool_id;variant_id=variant.rate_variant_id
 svc.bootstrap_calendar(hotel.hosted_hotel_id,{'start_date':'2026-08-25','end_date':'2026-09-10'})
 return hotel.hosted_hotel_id,offer_id,pool_id,variant_id
def body(offer_id,check_in='2026-09-01',check_out='2026-09-03'):
 return {'hosted_offer_id':offer_id,'guest_name':'测试住客','guest_contact':'0451-88800808','check_in':check_in,'check_out':check_out,'adults':2,'children':0,'extra_beds':0}

def test_dated_calendar_bootstrap_is_idempotent_and_shared_by_rate_variants():
 hotel_id,_,pool_id,_=setup();again=svc.bootstrap_calendar(hotel_id,{'start_date':'2026-09-01','end_date':'2026-09-02'})
 assert again['inventory_days_created']==0 and again['rate_days_created']==0
 with SessionLocal() as s:assert len(s.scalars(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==pool_id)).all())==17

def test_close_stop_sell_and_reopen_are_enforced():
 _,offer,pool,variant=setup();svc.set_inventory_day(pool,'2026-09-01',{'sale_state':'CLOSED'})
 with pytest.raises(ValueError,match='DATE_CLOSED_OR_STOP_SELL'):svc.reserve('aoluguya-harbin',body(offer),'closed')
 svc.set_inventory_day(pool,'2026-09-01',{'sale_state':'OPEN','capacity_available':50});svc.set_rate_day(variant,'2026-09-01',{'sale_state':'STOP_SELL'})
 with pytest.raises(ValueError,match='DATE_CLOSED_OR_STOP_SELL'):svc.reserve('aoluguya-harbin',body(offer),'stop')

def test_stay_advance_occupancy_children_and_extra_bed_rules_are_enforced():
 _,offer,_,variant=setup();svc.set_rate_day(variant,'2026-09-01',{'sale_state':'OPEN','min_stay':3,'max_stay':5,'advance_min_days':0,'advance_max_days':365,'max_adults':2,'max_children':0,'extra_bed_allowed':False})
 with pytest.raises(ValueError,match='STAY_OR_ADVANCE_RESTRICTION_FAILED'):svc.reserve('aoluguya-harbin',body(offer),'short')
 svc.set_rate_day(variant,'2026-09-01',{'sale_state':'OPEN','min_stay':1,'max_stay':5,'advance_min_days':0,'advance_max_days':365,'max_adults':2,'max_children':0,'extra_bed_allowed':False})
 with pytest.raises(ValueError,match='OCCUPANCY_OR_EXTRA_BED_RESTRICTION_FAILED'):svc.reserve('aoluguya-harbin',{**body(offer),'children':1},'child')

def test_atomic_daily_inventory_prevents_oversell_and_prices_each_night():
 _,offer,pool,_=setup();svc.set_inventory_day(pool,'2026-09-01',{'sale_state':'OPEN','capacity_total':1,'capacity_available':1});svc.set_inventory_day(pool,'2026-09-02',{'sale_state':'OPEN','capacity_total':1,'capacity_available':1})
 first=svc.reserve('aoluguya-harbin',body(offer),'first')
 with pytest.raises(ValueError,match='NO_DATED_INVENTORY'):svc.reserve('aoluguya-harbin',body(offer),'second')
 with SessionLocal() as s:
  nights=s.scalars(select(HostedReservationNightRow).where(HostedReservationNightRow.hosted_reservation_id==first['hosted_reservation_id'])).all();assert len(nights)==2 and first['amount_minor']==sum(x.price_minor for x in nights)

def test_go_page_and_phone_orders_share_inbox_notifications_and_audit_chain():
 _,offer,_,_=setup();web=svc.reserve('aoluguya-harbin',body(offer),'web','GO_PAGE','CONSUMER');phone=svc.reserve('aoluguya-harbin',body(offer),'phone','PHONE','frontdesk')
 with SessionLocal() as s:
  assert s.get(HostedReservationStayRow,web['hosted_reservation_id']).source=='GO_PAGE' and s.get(HostedReservationStayRow,phone['hosted_reservation_id']).source=='PHONE'
  assert s.query(HostedReservationNotificationRow).count()==4 and s.query(HostedDirectReservationEventRow).count()==2

def test_timeout_releases_every_night_without_payment_or_refund():
 _,offer,pool,_=setup();r=svc.reserve('aoluguya-harbin',body(offer),'timeout')
 with SessionLocal() as s:
  stay=s.get(HostedReservationStayRow,r['hosted_reservation_id']);stay.confirmation_expires_at=datetime.now(timezone.utc)-timedelta(minutes=1);s.commit()
 result=svc.expire_pending();assert result['expired_count']==1 and result['payment_live'] is False
 with SessionLocal() as s:
  assert s.get(HostedReservationStayRow,r['hosted_reservation_id']).operational_state=='EXPIRED';days=s.scalars(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==pool,HostedInventoryDayRow.stay_date.in_(['2026-09-01','2026-09-02']))).all();assert all(x.capacity_available==50 for x in days)

def test_confirm_cancel_and_atomic_reschedule_keep_no_payment_truth():
 _,offer,pool,_=setup();r=svc.reserve('aoluguya-harbin',body(offer),'ops');confirmed=svc.action(r['hosted_reservation_id'],{'action':'CONFIRM','hotel_confirmation_reference':'frontdesk-1'},'frontdesk');assert confirmed['payment_state']=='ALIPAY_APPLICATION_PENDING_NO_CHARGE'
 moved=svc.reschedule(r['hosted_reservation_id'],{'check_in':'2026-09-03','check_out':'2026-09-05'},'frontdesk');assert moved['check_in']=='2026-09-03' and moved['amount_minor']>0
 cancelled=svc.action(r['hosted_reservation_id'],{'action':'CANCEL'},'frontdesk');assert cancelled['payment_state']=='NO_PAYMENT_NO_REFUND_REQUIRED'
 with SessionLocal() as s:
  assert all(x.state=='RELEASED' for x in s.scalars(select(HostedReservationNightRow).where(HostedReservationNightRow.hosted_reservation_id==r['hosted_reservation_id'])).all())


@pytest.fixture(autouse=True)
def fixed_business_day(monkeypatch):
 class BusinessDate(date):
  @classmethod
  def today(cls):return cls(2026,8,25)
 monkeypatch.setattr('go_hotel.services.hosted_reservation_operations.date',BusinessDate)
