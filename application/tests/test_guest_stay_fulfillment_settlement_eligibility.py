import hashlib,pytest
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.alipay_safeguarded_settlement import alipay_safeguarded_settlement_service as pay
from go_hotel.services.guest_stay_fulfillment import guest_stay_fulfillment_service as svc
def setup():
 h=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin');o=booking.upsert_offer(h['hosted_hotel_id'],{'room_name':'测试房','rate_name':'测试价','price_minor':10000,'inventory':5,'cancellation_policy':'30分钟免费取消'},'hotel');booking.publish(h['hosted_hotel_id'],'hotel');r=booking.reserve('aoluguya-harbin',{'hosted_offer_id':o['hosted_offer_id'],'guest_name':'测试','guest_contact':'13800000000','check_in':'2026-09-01','check_out':'2026-09-03'},'r1');x=svc.create(r['hosted_reservation_id'],'frontdesk');return r,x
def checkin():
 r,x=setup();svc.identity(x['stay_lifecycle_id'],{'identity_evidence_hash':hashlib.sha256(b'id-ref').hexdigest(),'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'frontdesk');svc.arrive(x['stay_lifecycle_id'],'frontdesk');svc.assign_room(x['stay_lifecycle_id'],{'room_reference':'room://2401'},'frontdesk');svc.check_in(x['stay_lifecycle_id'],{'registration_evidence_reference':'hotel://registration'},'frontdesk');return r,x
def test_pre_arrival_is_idempotent_and_incomplete_stay_cannot_settle():
 r,x=setup();again=svc.create(r['hosted_reservation_id'],'frontdesk');d=svc.eligibility(x['stay_lifecycle_id']);assert again['stay_lifecycle_id']==x['stay_lifecycle_id'] and d['decision']=='BLOCKED' and 'STAY_NOT_COMPLETED' in d['blockers_json']
def test_identity_stores_hash_reference_and_checkin_requires_identity_room_registration():
 r,x=setup();svc.arrive(x['stay_lifecycle_id'],'frontdesk')
 with pytest.raises(ValueError,match='IDENTITY_ROOM_AND_REGISTRATION_REQUIRED'):svc.check_in(x['stay_lifecycle_id'],{},'frontdesk')
 e=svc.identity(x['stay_lifecycle_id'],{'identity_evidence_hash':hashlib.sha256(b'id').hexdigest(),'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'frontdesk');assert e['state']=='VERIFIED_REFERENCE_ONLY'
def test_room_assignment_change_and_extension_are_evidenced():
 r,x=checkin();svc.assign_room(x['stay_lifecycle_id'],{'room_reference':'room://2501','evidence_reference':'hotel://change'},'manager');e=svc.extend(x['stay_lifecycle_id'],{'new_check_out':'2026-09-04','inventory_extension_reference':'inventory://held'},'frontdesk');t=svc.timeline(x['stay_lifecycle_id']);assert e['planned_check_out']=='2026-09-04' and any(v['event_type']=='ROOM_CHANGED' for v in t['events'])
def test_dual_checkout_evidence_enables_contract_only_eligibility_without_payment():
 r,x=checkin();svc.checkout(x['stay_lifecycle_id'],{'hotel_fulfillment_evidence':'hotel://folio','guest_checkout_reference':'guest://checkout','fulfilled_amount_minor':10000},'frontdesk');d=svc.eligibility(x['stay_lifecycle_id']);assert d['decision']=='ELIGIBLE_CONTRACT_ONLY' and d['eligible_amount_minor']==10000 and d['external_payment_invoked'] is False
def test_early_checkout_supports_partial_fulfillment_amount():
 r,x=checkin();svc.checkout(x['stay_lifecycle_id'],{'hotel_fulfillment_evidence':'hotel://early','guest_checkout_reference':'guest://early','fulfilled_amount_minor':5000},'frontdesk');d=svc.eligibility(x['stay_lifecycle_id']);assert d['eligible_amount_minor']==5000
def test_open_dispute_freezes_otherwise_eligible_settlement():
 r,x=checkin();svc.checkout(x['stay_lifecycle_id'],{'hotel_fulfillment_evidence':'hotel://folio','guest_checkout_reference':'guest://checkout'},'frontdesk');svc.dispute(x['stay_lifecycle_id'],{'dispute_type':'SERVICE','description':'异议','evidence_reference':'guest://complaint'},'guest');d=svc.eligibility(x['stay_lifecycle_id']);assert d['decision']=='BLOCKED' and 'OPEN_FULFILLMENT_DISPUTE' in d['blockers_json']
def test_no_show_requires_preapproved_amount_and_evidence():
 r,x=setup();a=pay.authorize(r['hosted_reservation_id'],{'mode':'CONTRACT_DRY_RUN'},'a1')
 with pytest.raises(ValueError,match='APPROVED_NO_SHOW_EVIDENCE_REQUIRED'):svc.no_show(x['stay_lifecycle_id'],{'hotel_no_show_evidence':'hotel://noshow'},'manager')
 p=pay.request_adjustment(a['authorization_id'],{'adjustment_type':'NO_SHOW','amount_minor':3000},'maker');pay.approve_adjustment(p['adjustment_approval_id'],{'evidence_reference':'policy://accepted'},'checker');svc.no_show(x['stay_lifecycle_id'],{'hotel_no_show_evidence':'hotel://noshow'},'manager');d=svc.eligibility(x['stay_lifecycle_id']);assert d['eligible_amount_minor']==3000 and d['external_payment_invoked'] is False
def test_timeline_explicitly_remains_non_live():
 r,x=checkin();t=svc.timeline(x['stay_lifecycle_id']);assert t['payment_live'] is False and t['production_live'] is False and len(t['events'])>=5
