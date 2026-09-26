from tests.hosted_review_support import legacy_publication
import hashlib,pytest
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.alipay_safeguarded_settlement import alipay_safeguarded_settlement_service as pay
from go_hotel.services.guest_stay_fulfillment import guest_stay_fulfillment_service as stay
from go_hotel.services.post_stay_dispute import post_stay_dispute_service as svc
def setup():
 h=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin');o=booking.upsert_offer(h['hosted_hotel_id'],{'room_name':'测试房','rate_name':'测试价','price_minor':10000,'inventory':5,'cancellation_policy':'30分钟免费取消'},'hotel');legacy_publication(h['hosted_hotel_id']);r=booking.reserve('aoluguya-harbin',{'hosted_offer_id':o['hosted_offer_id'],'guest_name':'测试','guest_contact':'13800000000','check_in':'2026-09-01','check_out':'2026-09-02'},'r1');x=stay.create(r['hosted_reservation_id'],'frontdesk');stay.identity(x['stay_lifecycle_id'],{'identity_evidence_hash':hashlib.sha256(b'id').hexdigest(),'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'frontdesk');stay.arrive(x['stay_lifecycle_id'],'frontdesk');stay.assign_room(x['stay_lifecycle_id'],{'room_reference':'room://1'},'frontdesk');stay.check_in(x['stay_lifecycle_id'],{'registration_evidence_reference':'hotel://reg'},'frontdesk');stay.checkout(x['stay_lifecycle_id'],{'hotel_fulfillment_evidence':'hotel://folio','guest_checkout_reference':'guest://checkout'},'frontdesk');stay.eligibility(x['stay_lifecycle_id']);pay.authorize(r['hosted_reservation_id'],{'mode':'CONTRACT_DRY_RUN'},'a1');c=svc.open_case(x['stay_lifecycle_id'],{'opened_by_party':'GUEST','dispute_type':'SERVICE','assigned_to':'go-case-owner','initial_evidence_reference':'guest://initial'},'guest');return x,c
def decision(case_id,amount=5000,outcome='PARTIAL_REFUND'):
 d=svc.request_decision(case_id,{'outcome':outcome,'refund_amount_minor':amount},'maker');return svc.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'go://decision'},'checker')
def test_three_party_case_types_and_open_case_freeze_settlement():
 x,c=setup();d=stay.eligibility(x['stay_lifecycle_id']);assert c['state']=='OPEN_EVIDENCE_COLLECTION' and d['decision']=='BLOCKED' and 'OPEN_FULFILLMENT_DISPUTE' in d['blockers_json']
def test_image_file_communication_timeline_evidence_and_responses():
 x,c=setup();e=svc.evidence(c['dispute_case_id'],{'submitted_by_party':'HOTEL','evidence_type':'IMAGE','storage_reference':'hotel://photo','content_hash':hashlib.sha256(b'photo').hexdigest()});r=svc.respond(c['dispute_case_id'],{'party':'GUEST','message_reference':'guest://statement'});assert e['evidence_type']=='IMAGE' and len(r['message_hash'])==64
def test_sla_escalation_and_mediation_are_evidenced():
 x,c=setup();e=svc.escalate(c['dispute_case_id'],{'force_for_test':True,'escalate_to':'duty-manager'},'system');m=svc.mediate(c['dispute_case_id'],{'recommendation':'PARTIAL_REFUND','recommended_refund_minor':5000,'rationale_reference':'go://mediation'},'mediator');assert e['state']=='SLA_ESCALATED' and m['recommended_refund_minor']==5000
def test_decision_requires_maker_checker_and_blocks_excess_refund():
 x,c=setup();d=svc.request_decision(c['dispute_case_id'],{'outcome':'FULL_REFUND','refund_amount_minor':20000},'maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'x'},'maker')
 with pytest.raises(ValueError,match='REFUND_EXCEEDS'):svc.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'x'},'checker')
def test_partial_refund_is_contract_only_idempotent_and_never_executes():
 x,c=setup();d=decision(c['dispute_case_id']);a=svc.refund_eligibility(d['post_stay_decision_id']);b=svc.refund_eligibility(d['post_stay_decision_id']);assert a['refund_eligibility_id']==b['refund_eligibility_id'] and a['decision']=='REFUND_ELIGIBLE_CONTRACT_ONLY' and a['external_refund_invoked'] is False
 with pytest.raises(ValueError,match='REAL_ALIPAY_REFUND_EXECUTOR_NOT_CONFIGURED'):svc.execute_refund(a['refund_eligibility_id'])
def test_no_refund_requires_zero_and_produces_no_refund_eligibility():
 x,c=setup();d=decision(c['dispute_case_id'],0,'NO_REFUND');r=svc.refund_eligibility(d['post_stay_decision_id']);assert r['decision']=='NO_REFUND_ELIGIBLE' and r['eligible_amount_minor']==0
def test_joint_reconciliation_detects_and_records_contract_amounts():
 x,c=setup();d=decision(c['dispute_case_id']);svc.refund_eligibility(d['post_stay_decision_id']);r=svc.reconcile(c['dispute_case_id']);assert r['settlement_eligible_minor']==10000 and r['refund_eligible_minor']==5000 and r['decision']=='CONTRACT_RECONCILED' and len(r['evidence_hash'])==64
def test_case_close_requires_decision_and_creates_immutable_summary_hash():
 x,c=setup()
 with pytest.raises(ValueError,match='APPROVED_DECISION_REQUIRED_FOR_CLOSURE'):svc.close(c['dispute_case_id'],{'closure_evidence_reference':'go://close'},'manager')
 decision(c['dispute_case_id']);closed=svc.close(c['dispute_case_id'],{'closure_evidence_reference':'go://close'},'manager');assert closed['state']=='CLOSED' and len(closed['closure_hash'])==64
