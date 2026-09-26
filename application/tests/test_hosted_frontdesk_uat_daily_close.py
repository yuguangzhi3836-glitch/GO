from tests.hosted_review_support import legacy_publication,identity,fare_hash
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectRateVariantRow,HostedGuestAccessAuditRow,HostedDailyCloseRow
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.aoluguya_inventory import configure_aoluguya_legacy_fixture as configure_aoluguya
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as svc,UAT
def setup():
 booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin');configure_aoluguya()
 with SessionLocal() as s:h=s.scalar(select(HostedDirectHotelRow));v=s.scalar(select(HostedDirectRateVariantRow));hotel_id=h.hosted_hotel_id;offer=v.hosted_offer_id
 ops.bootstrap_calendar(hotel_id,{'start_date':'2026-09-01','end_date':'2026-09-10'});return hotel_id,offer
def roles(h):
 global FRONTDESK,RESERVATIONS,MANAGER
 grantor,_=legacy_publication(h)
 staff=[]
 for label,role in [('frontdesk','FRONT_DESK'),('reservations','RESERVATIONS'),('manager','DUTY_MANAGER')]:
  principal,_=identity(label);staff.append(principal.user_id)
  svc.assign_role(h,{'staff_id':principal.user_id,'role':role,'evidence_reference':'isolated://staff'},grantor)
 FRONTDESK,RESERVATIONS,MANAGER=staff
def body(offer):return {'hosted_offer_id':offer,'expected_fare_rule_hash':fare_hash(offer),'guest_name':'张三','guest_contact':'13800000000','check_in':'2026-09-01','check_out':'2026-09-02'}
def test_hotel_staff_roles_are_required_and_evidence_bound():
 h,_=setup()
 with pytest.raises(ValueError,match='VALID_STAFF_ROLE_EVIDENCE_REQUIRED'):svc.assign_role(h,{'staff_id':'x','role':'FRONT_DESK'},'admin')
 roles(h);assert svc.dashboard(h)['active_staff_roles']==3
def test_shift_handover_captures_unresolved_inbox():
 h,o=setup();roles(h);r=ops.reserve('aoluguya-harbin',body(o),'r1');x=svc.handover(h,{'incoming_staff_id':RESERVATIONS,'notes':'夜班交接'},FRONTDESK);assert r['hosted_reservation_id'] in x['unresolved_reservation_ids_json'] and x['state']=='ACCEPTED'
def test_guest_data_is_masked_and_unmask_is_manager_audited():
 h,o=setup();roles(h);r=ops.reserve('aoluguya-harbin',body(o),'r1');a=svc.guest_view(r['hosted_reservation_id'],{'reason':'办理入住'},FRONTDESK);b=svc.guest_view(r['hosted_reservation_id'],{'reason':'经理核验','unmask':True},MANAGER);assert '*' in a['guest_contact'] and b['guest_contact']=='13800000000'
 with SessionLocal() as s:assert s.query(HostedGuestAccessAuditRow).count()==2
def test_phone_duplicate_requires_review_evidence_and_unifies_order():
 h,o=setup();roles(h);first=svc.phone_reserve('aoluguya-harbin',body(o),'p1',FRONTDESK)
 with pytest.raises(ValueError,match='POSSIBLE_DUPLICATE_REQUIRES_REVIEW'):svc.phone_reserve('aoluguya-harbin',body(o),'p2',FRONTDESK)
 second=svc.phone_reserve('aoluguya-harbin',{**body(o),'duplicate_review_evidence':'hotel://verified-different-guest'},'p2',FRONTDESK);assert first['hosted_reservation_id']!=second['hosted_reservation_id']
def test_reject_cancel_reschedule_require_manager_maker_checker():
 h,o=setup();roles(h);r=ops.reserve('aoluguya-harbin',body(o),'r1');a=svc.request_action(r['hosted_reservation_id'],{'action_type':'REJECT'},FRONTDESK)
 with pytest.raises(ValueError,match='MAKER_CHECKER_SEPARATION_REQUIRED'):svc.approve_action(a['action_approval_id'],{'evidence_reference':'same-maker'},FRONTDESK)
 done=svc.approve_action(a['action_approval_id'],{'evidence_reference':'manager://approved'},MANAGER);assert done['reservation']['reservation_state']=='HOTEL_REJECTED' and done['payment_live'] is False
def test_sla_manager_alert_and_printable_arrival_voucher():
 h,o=setup();roles(h);r=ops.reserve('aoluguya-harbin',body(o),'r1');e=svc.escalate(h,FRONTDESK);v=svc.voucher(r['hosted_reservation_id'],FRONTDESK);assert e['escalations_created']==1 and e['manager_alert_state']=='QUEUED_NOT_SENT' and v['printable'] and v['payment_captured'] is False
def test_daily_close_is_idempotent_and_contains_zero_payment_truth():
 h,o=setup();roles(h);ops.reserve('aoluguya-harbin',body(o),'r1');a=svc.daily_close(h,{'business_date':'2026-09-01'},MANAGER);b=svc.daily_close(h,{'business_date':'2026-09-01'},MANAGER);assert a['daily_close_id']==b['daily_close_id'] and a['exception_summary_json']['payment_transactions']==0 and len(a['evidence_hash'])==64
def test_uat_requires_manager_evidence_and_all_scenarios():
 h,_=setup();roles(h)
 with pytest.raises(ValueError,match='VALID_UAT_PASS_EVIDENCE_REQUIRED'):svc.uat(h,{'scenario_key':'CONFIRM','result':'FAIL'},MANAGER)
 result=None
 for key in UAT:result=svc.uat(h,{'scenario_key':key,'result':'PASS','evidence_reference':f'hotel-uat://{key}'},MANAGER)
 assert result['operations_uat_complete'] is True and result['production_live'] is False


import pytest
from datetime import date
@pytest.fixture(autouse=True)
def fixed_business_day(monkeypatch):
 class BusinessDate(date):
  @classmethod
  def today(cls):return cls(2026,8,25)
 monkeypatch.setattr('go_hotel.services.hosted_reservation_operations.date',BusinessDate)
