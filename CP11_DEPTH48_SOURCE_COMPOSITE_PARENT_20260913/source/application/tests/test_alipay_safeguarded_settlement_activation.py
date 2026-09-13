import hashlib,hmac,json,pytest
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.alipay_safeguarded_settlement import alipay_safeguarded_settlement_service as svc
def setup():
 h=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin');o=booking.upsert_offer(h['hosted_hotel_id'],{'room_name':'测试房','rate_name':'测试价','price_minor':10000,'inventory':5,'cancellation_policy':'30分钟免费取消'},'hotel');booking.publish(h['hosted_hotel_id'],'hotel');r=booking.reserve('aoluguya-harbin',{'hosted_offer_id':o['hosted_offer_id'],'guest_name':'测试','guest_contact':'13800000000','check_in':'2026-09-01','check_out':'2026-09-02'},'r1');return h,r
def auth():
 h,r=setup();a=svc.authorize(r['hosted_reservation_id'],{'mode':'CONTRACT_DRY_RUN'},'auth1');return h,r,a
def test_existing_account_is_attested_but_activation_gate_remains_blocked():
 h,_=setup();m=svc.bind_merchant(h['hosted_hotel_id'],{'merchant_account_name':'哈尔滨敖麓谷雅酒店'});g=svc.gate(h['hosted_hotel_id']);assert m['account_attestation_state']=='EXISTS_USER_ATTESTED' and 'SANDBOX_APP_ID_REQUIRED' in g['blockers'] and g['external_sandbox_certified'] is False
def test_credentials_accept_references_only_and_never_plain_private_key():
 h,_=setup();m=svc.bind_merchant(h['hosted_hotel_id'],{'merchant_account_name':'哈尔滨敖麓谷雅酒店','app_id_reference':'app://pending','product_contract_reference':'contract://pending'})
 with pytest.raises(ValueError,match='EXTERNAL_KEY'):svc.credentials(m['merchant_binding_id'],{'app_public_key_reference':'plain','alipay_public_key_reference':'plain','kms_private_key_reference':'secret'})
 c=svc.credentials(m['merchant_binding_id'],{'app_public_key_reference':'cert://app','alipay_public_key_reference':'cert://alipay','kms_private_key_reference':'kms://alipay/private'});assert c['state']=='REFERENCE_BOUND_NOT_EXTERNALLY_VERIFIED'
def test_external_authorization_is_hard_blocked_but_contract_dry_run_is_truthful_and_idempotent():
 h,r=setup()
 with pytest.raises(ValueError,match='EXTERNAL_ALIPAY_SANDBOX_EXECUTOR_NOT_CONFIGURED'):svc.authorize(r['hosted_reservation_id'],{'mode':'EXTERNAL_SANDBOX'},'x')
 a=svc.authorize(r['hosted_reservation_id'],{'mode':'CONTRACT_DRY_RUN'},'x');b=svc.authorize(r['hosted_reservation_id'],{'mode':'CONTRACT_DRY_RUN'},'x');assert a['authorization_id']==b['authorization_id'] and a['external_invoked'] is False
def test_free_cancel_hotel_reject_timeout_release_contract_without_external_claim():
 _,_,a=auth();r=svc.release(a['authorization_id'],{'reason':'FREE_CANCELLATION'},'system');assert r['state']=='CONTRACT_RELEASED_NOT_ALIPAY' and r['external_invoked'] is False
def test_fulfillment_gate_is_required_before_contract_capture_and_no_settlement_claimed():
 _,_,a=auth()
 with pytest.raises(ValueError,match='FULFILLMENT_SETTLEMENT_GATE_REQUIRED'):svc.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
 svc.fulfill(a['authorization_id'],{'hotel_fulfillment_evidence':'hotel://checkout','guest_checkout_reference':'checkout://1'},'manager');c=svc.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'});assert c['state']=='CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED'
def test_no_show_and_cancellation_fee_require_maker_checker():
 _,_,a=auth();x=svc.request_adjustment(a['authorization_id'],{'adjustment_type':'NO_SHOW','amount_minor':5000},'maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_adjustment(x['adjustment_approval_id'],{'evidence_reference':'e'},'maker')
 y=svc.approve_adjustment(x['adjustment_approval_id'],{'evidence_reference':'hotel://policy-accepted'},'checker');assert y['state']=='APPROVED_CONTRACT_ONLY'
def test_webhook_signature_and_replay_idempotency_contract():
 _,_,a=auth();old=settings.alipay_webhook_verification_key;settings.alipay_webhook_verification_key='test-key'
 try:
  b={'authorization_id':a['authorization_id'],'external_event_id':'evt-1','event_type':'AUTH_STATUS'};raw=json.dumps(b,sort_keys=True,separators=(',',':'));sig=hmac.new(b'test-key',raw.encode(),hashlib.sha256).hexdigest();one=svc.webhook(b,sig);two=svc.webhook(b,sig);assert one['duplicate'] is False and two['duplicate'] is True
  with pytest.raises(ValueError,match='SIGNATURE_INVALID'):svc.webhook({**b,'external_event_id':'evt-2'},'bad')
 finally:settings.alipay_webhook_verification_key=old
def test_joint_reconciliation_evidence_never_claims_external_settlement():
 _,_,a=auth();r=svc.reconcile(a['authorization_id']);assert r['decision']=='CONTRACT_ONLY_NOT_EXTERNAL_RECONCILED' and r['settlement_amount_minor']==0 and len(r['evidence_hash'])==64
