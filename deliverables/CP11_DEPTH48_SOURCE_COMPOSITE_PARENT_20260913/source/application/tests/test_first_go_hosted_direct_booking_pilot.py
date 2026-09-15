import pytest
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as svc
def setup():
 h=svc.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin');o=svc.upsert_offer(h['hosted_hotel_id'],{'room_name':'豪华大床房','rate_name':'酒店官方价','price_minor':128800,'inventory':2,'cancellation_policy':'入住前24小时可取消'},'hotel');svc.publish(h['hosted_hotel_id'],'hotel');return h,o
def reserve(key='r1'):
 _,o=setup();return svc.reserve('aoluguya-harbin',{'hosted_offer_id':o['hosted_offer_id'],'guest_name':'测试住客','guest_contact':'13800000000','check_in':'2026-09-01','check_out':'2026-09-02'},key)
def test_first_pilot_supplier_is_locked():
 with pytest.raises(ValueError,match='FIRST_PILOT_SUPPLIER_LOCKED'):svc.create_hotel({'supplier_name':'其他酒店'},'admin')
def test_page_requires_active_offer_before_publish():
 h=svc.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店'},'admin')
 with pytest.raises(ValueError,match='ACTIVE_ROOM_OFFER_REQUIRED'):svc.publish(h['hosted_hotel_id'],'hotel')
def test_published_page_discloses_reservation_only_and_alipay_pending():
 setup();p=svc.page('aoluguya-harbin');assert p['booking_mode']=='RESERVATION_REQUEST_ONLY' and p['payment_available'] is False and p['payment']['application_state']=='SANDBOX_APPLICATION_NOT_CREATED'
def test_reservation_is_idempotent_and_never_attempts_payment():
 _,o=setup();body={'hosted_offer_id':o['hosted_offer_id'],'guest_name':'测试','guest_contact':'13800000000','check_in':'2026-09-01','check_out':'2026-09-02'};a=svc.reserve('aoluguya-harbin',body,'same');b=svc.reserve('aoluguya-harbin',body,'same');assert a['hosted_reservation_id']==b['hosted_reservation_id'] and a['payment_state']=='ALIPAY_APPLICATION_PENDING_NO_CHARGE'
def test_hotel_confirmation_does_not_claim_payment_success():
 r=reserve();d=svc.hotel_decision(r['hosted_reservation_id'],{'decision':'CONFIRM'},'hotel');assert d['reservation_state']=='HOTEL_CONFIRMED_AWAITING_ALIPAY_ONBOARDING' and d['payment_state']=='ALIPAY_APPLICATION_PENDING_NO_CHARGE'
def test_rejection_and_cancel_restore_inventory_without_refund():
 _,o=setup();body={'hosted_offer_id':o['hosted_offer_id'],'guest_name':'测试','guest_contact':'13800000000','check_in':'2026-09-01','check_out':'2026-09-02'};r=svc.reserve('aoluguya-harbin',body,'r1');d=svc.hotel_decision(r['hosted_reservation_id'],{'decision':'REJECT'},'hotel');assert d['reservation_state']=='HOTEL_REJECTED';r2=svc.reserve('aoluguya-harbin',body,'r2');c=svc.cancel(r2['hosted_reservation_id'],'consumer');assert c['payment_state']=='NO_PAYMENT_NO_REFUND_REQUIRED'
def test_status_truthfully_reports_no_payment_and_not_live():
 r=reserve();s=svc.status(r['hosted_reservation_id']);assert s['payment_attempted'] is False and s['production_live'] is False and s['events'][0]['payload_json']['payment_attempted'] is False
