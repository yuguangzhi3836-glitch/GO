import hashlib,hmac,json
from sqlalchemy import select,text
from contextlib import contextmanager
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectReservationRow,HostedReservationStayRow,HostedDirectRoomOfferRow,AlipayMerchantBindingRow,AlipayCredentialBindingRow,AlipayAuthorizationRow,AlipaySafeguardedEventRow,AlipayAdjustmentApprovalRow,AlipayReconciliationRow
from go_hotel.services.hosted_direct_booking import ident,now,out
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
@contextmanager
def transaction():
 with SessionLocal() as s:
  if s.bind.dialect.name=='sqlite':s.execute(text('BEGIN IMMEDIATE'))
  try:yield s;s.commit()
  except BaseException:s.rollback();raise

def locked_authorization(s,aid):
 probe=s.get(AlipayAuthorizationRow,aid)
 if not probe:raise ValueError('AUTHORIZATION_NOT_FOUND')
 from go_hotel.services.hosted_credit_value import lock_sources
 lock_sources(s,probe.hosted_reservation_id)
 stay=s.get(HostedReservationStayRow,probe.hosted_reservation_id,with_for_update=True)
 reservation=s.get(HostedDirectReservationRow,probe.hosted_reservation_id,with_for_update=True)
 authorization=s.get(AlipayAuthorizationRow,aid,with_for_update=True,populate_existing=True)
 return authorization,reservation,stay

class Service:
 def bind_merchant(self,hotel_id,b):
  if b.get('merchant_account_name')!='哈尔滨敖麓谷雅酒店':raise ValueError('HOTEL_MERCHANT_ACCOUNT_NAME_REQUIRED')
  with SessionLocal() as s:
   if not s.get(HostedDirectHotelRow,hotel_id):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   r=AlipayMerchantBindingRow(merchant_binding_id=ident('amb'),hosted_hotel_id=hotel_id,merchant_account_name=b['merchant_account_name'],account_attestation_state='EXISTS_USER_ATTESTED',app_id_reference=b.get('app_id_reference'),product_contract_reference=b.get('product_contract_reference'),state='PENDING_OPEN_PLATFORM_ARTIFACTS',updated_at=now());s.add(r);s.commit();return out(r)
 def credentials(self,binding_id,b):
  refs=[b.get(x) for x in ('app_public_key_reference','alipay_public_key_reference','kms_private_key_reference')]
  if not all(refs) or any(not str(x).startswith(('kms://','vault://','cert://')) for x in refs):raise ValueError('EXTERNAL_KEY_AND_CERTIFICATE_REFERENCES_REQUIRED')
  with SessionLocal() as s:
   m=s.get(AlipayMerchantBindingRow,binding_id)
   if not m:raise ValueError('MERCHANT_BINDING_NOT_FOUND')
   r=AlipayCredentialBindingRow(credential_binding_id=ident('acb'),merchant_binding_id=binding_id,app_public_key_reference=refs[0],alipay_public_key_reference=refs[1],kms_private_key_reference=refs[2],certificate_mode=bool(b.get('certificate_mode',True)),state='REFERENCE_BOUND_NOT_EXTERNALLY_VERIFIED',updated_at=now());s.add(r)
   if m.app_id_reference and m.product_contract_reference:m.state='READY_FOR_EXTERNAL_SANDBOX_EXECUTOR'
   s.commit();return out(r)
 def gate(self,hotel_id):
  with SessionLocal() as s:
   m=s.scalar(select(AlipayMerchantBindingRow).where(AlipayMerchantBindingRow.hosted_hotel_id==hotel_id));cred=s.scalar(select(AlipayCredentialBindingRow).where(AlipayCredentialBindingRow.merchant_binding_id==m.merchant_binding_id)) if m else None;block=[]
   if not m:block.append('MERCHANT_BINDING_REQUIRED')
   else:
    if not m.app_id_reference:block.append('SANDBOX_APP_ID_REQUIRED')
    if not m.product_contract_reference:block.append('AUTHORIZATION_PRODUCT_CONTRACT_REQUIRED')
    if not cred:block.append('KMS_CERTIFICATE_BINDING_REQUIRED')
   block.append('REAL_ALIPAY_SANDBOX_EXECUTOR_NOT_CONFIGURED')
   return {'state':'BLOCKED_PENDING_EXTERNAL_ALIPAY_ARTIFACTS','blockers':block,'merchant_account_exists_user_attested':bool(m),'external_sandbox_certified':False,'payment_live':False,'production_live':False}
 def authorize(self,reservation_id,b,key):
  if b.get('mode')!='CONTRACT_DRY_RUN':raise ValueError('EXTERNAL_ALIPAY_SANDBOX_EXECUTOR_NOT_CONFIGURED')
  if not key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  with transaction() as s:
   s.get(HostedReservationStayRow,reservation_id,with_for_update=True)
   r=s.get(HostedDirectReservationRow,reservation_id,with_for_update=True)
   if not r:raise ValueError('RESERVATION_NOT_FOUND')
   old=s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.idempotency_key==key))
   if old:
    if (old.hosted_reservation_id,old.amount_minor,old.currency)!=(reservation_id,r.amount_minor,r.currency):raise ValueError('AUTHORIZATION_IDEMPOTENCY_CONFLICT')
    return out(old)
   if r.reservation_state not in {'PENDING_HOTEL_CONFIRMATION','HOTEL_CONFIRMED_AWAITING_ALIPAY_ONBOARDING'}:raise ValueError('RESERVATION_NOT_AUTHORIZABLE')
   active=s.scalars(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==reservation_id,AlipayAuthorizationRow.state!='CONTRACT_RELEASED_NOT_ALIPAY')).all()
   if active:
    if len(active)!=1 or active[0].amount_minor!=r.amount_minor:raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
    return out(active[0])
   if s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==reservation_id)):raise ValueError('RELEASED_AUTHORIZATION_REBOOK_REQUIRED')
   a=AlipayAuthorizationRow(authorization_id=ident('aauth'),hosted_reservation_id=reservation_id,amount_minor=r.amount_minor,currency=r.currency,state='CONTRACT_FROZEN_NOT_ALIPAY',external_invoked=False,external_authorization_reference=None,settlement_eligible=False,idempotency_key=key,updated_at=now());s.add(a);s.flush();self._event(s,a.authorization_id,'AUTHORIZATION_CONTRACT_FROZEN',{'amount_minor':a.amount_minor},False,False)
   return out(a)
 def release(self,authorization_id,b,actor):
  if b.get('reason') not in ('FREE_CANCELLATION','HOTEL_REJECTED','CONFIRMATION_TIMEOUT'):raise ValueError('VALID_AUTOMATIC_RELEASE_REASON_REQUIRED')
  with transaction() as s:
   a,r,stay=locked_authorization(s,authorization_id)
   if a.state=='CONTRACT_RELEASED_NOT_ALIPAY':return out(a)
   if a.state!='CONTRACT_FROZEN_NOT_ALIPAY' or a.external_invoked:raise ValueError('AUTHORIZATION_NOT_RELEASABLE')
   from go_hotel.services import hosted_money
   hosted_money.release(s,a,b['reason'])
   a.state='CONTRACT_RELEASED_NOT_ALIPAY';a.updated_at=now()
   if r.payment_state=='CONTRACT_AUTHORIZED_NOT_ALIPAY':r.payment_state='NO_PAYMENT_NO_REFUND_REQUIRED';r.updated_at=now()
   self._event(s,a.authorization_id,'AUTHORIZATION_RELEASED',{'reason':b['reason'],'actor':actor},False,False)
   hosted_money.project(s,r,'FUNDS_RELEASED')
   return out(a)
 def fulfill(self,authorization_id,b,actor):
  if not b.get('hotel_fulfillment_evidence') or not b.get('guest_checkout_reference'):raise ValueError('FULFILLMENT_AND_CHECKOUT_EVIDENCE_REQUIRED')
  with transaction() as s:
   a,r,stay=locked_authorization(s,authorization_id)
   if a.state in {'FULFILLED_ELIGIBLE_FOR_CONTRACT_CAPTURE','CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED'}:return out(a)
   if a.state!='CONTRACT_FROZEN_NOT_ALIPAY' or a.external_invoked:raise ValueError('AUTHORIZATION_NOT_FULFILLABLE')
   if r.payment_state=='CONTRACT_AUTHORIZED_NOT_ALIPAY' and (not stay or stay.operational_state!='CONFIRMED'):raise ValueError('HOTEL_CONFIRMATION_REQUIRED_BEFORE_FULFILLMENT')
   from go_hotel.services import hosted_money
   if hosted_money.root(s,a):
    guest,proof=hosted_money.fulfillment(s,r,a)
    if (b['hotel_fulfillment_evidence'],b['guest_checkout_reference'])!=(proof.hotel_evidence_reference,proof.guest_checkout_reference):raise ValueError('FULFILLMENT_REFERENCE_MISMATCH')
   a.state='FULFILLED_ELIGIBLE_FOR_CONTRACT_CAPTURE';a.settlement_eligible=True;a.updated_at=now();self._event(s,a.authorization_id,'FULFILLMENT_CONFIRMED',b,False,False)
   return out(a)
 def capture(self,authorization_id,b):
  if b.get('mode')!='CONTRACT_DRY_RUN':raise ValueError('EXTERNAL_ALIPAY_SANDBOX_EXECUTOR_NOT_CONFIGURED')
  with transaction() as s:
   a,r,stay=locked_authorization(s,authorization_id)
   if a.state=='CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED' or a.state=='CONTRACT_RELEASED_NOT_ALIPAY' and a.settlement_eligible:return out(a)
   if a.state!='FULFILLED_ELIGIBLE_FOR_CONTRACT_CAPTURE' or not a.settlement_eligible or a.external_invoked:raise ValueError('FULFILLMENT_SETTLEMENT_GATE_REQUIRED')
   from go_hotel.services import hosted_money
   amount=hosted_money.settle(s,r,stay,a) if hosted_money.root(s,a) else a.amount_minor
   a.state='CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED' if amount else 'CONTRACT_RELEASED_NOT_ALIPAY';a.updated_at=now()
   if r.payment_state=='CONTRACT_AUTHORIZED_NOT_ALIPAY':r.payment_state='CONTRACT_CAPTURED_NOT_ALIPAY' if amount else 'NO_PAYMENT_NO_REFUND_REQUIRED';r.updated_at=now()
   if r.payment_state=='CONTRACT_CREDIT_AND_AUTHORIZED':r.payment_state='CONTRACT_CREDIT_PAID';r.updated_at=now()
   self._event(s,a.authorization_id,'CAPTURE_CONTRACT_VALIDATED',{'amount_minor':amount},False,False)
   hosted_money.project(s,r,'FULFILLMENT_FUNDS_SETTLED')
   return out(a)
 def request_adjustment(self,authorization_id,b,actor):
  if b.get('adjustment_type') not in ('NO_SHOW','CANCELLATION_FEE') or int(b.get('amount_minor',0))<=0:raise ValueError('VALID_NO_SHOW_OR_CANCELLATION_FEE_REQUIRED')
  with SessionLocal() as s:
   if not s.get(AlipayAuthorizationRow,authorization_id):raise ValueError('AUTHORIZATION_NOT_FOUND')
   r=AlipayAdjustmentApprovalRow(adjustment_approval_id=ident('aadj'),authorization_id=authorization_id,adjustment_type=b['adjustment_type'],amount_minor=int(b['amount_minor']),requester_id=actor,checker_id=None,evidence_reference=None,state='PENDING_CHECKER',created_at=now());s.add(r);s.commit();return out(r)
 def approve_adjustment(self,approval_id,b,actor):
  if not b.get('evidence_reference'):raise ValueError('ADJUSTMENT_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   r=s.get(AlipayAdjustmentApprovalRow,approval_id)
   if not r or r.state!='PENDING_CHECKER':raise ValueError('ADJUSTMENT_NOT_PENDING')
   if r.requester_id==actor:raise ValueError('MAKER_CHECKER_SEPARATION_REQUIRED')
   r.checker_id=actor;r.evidence_reference=b['evidence_reference'];r.state='APPROVED_CONTRACT_ONLY';s.commit();return out(r)
 def webhook(self,b,signature):
  key=settings.alipay_webhook_verification_key
  if not key:raise ValueError('ALIPAY_WEBHOOK_VERIFICATION_KEY_NOT_CONFIGURED')
  raw=json.dumps(b,sort_keys=True,separators=(',',':'));expected=hmac.new(key.encode(),raw.encode(),hashlib.sha256).hexdigest()
  if not hmac.compare_digest(expected,signature):raise ValueError('ALIPAY_WEBHOOK_SIGNATURE_INVALID')
  with SessionLocal() as s:
   old=s.scalar(select(AlipaySafeguardedEventRow).where(AlipaySafeguardedEventRow.external_event_id==b['external_event_id']))
   if old:return {'duplicate':True,'event':out(old)}
   a=s.get(AlipayAuthorizationRow,b['authorization_id'])
   if not a:raise ValueError('AUTHORIZATION_NOT_FOUND')
   e=self._event(s,a.authorization_id,b['event_type'],b,True,True,b['external_event_id']);s.commit();return {'duplicate':False,'event':out(e)}
 def reconcile(self,authorization_id):
  with SessionLocal() as s:
   a=s.get(AlipayAuthorizationRow,authorization_id)
   if not a:raise ValueError('AUTHORIZATION_NOT_FOUND')
   from go_hotel.services import hosted_money
   funds=hosted_money.summary(s,s.get(HostedDirectReservationRow,a.hosted_reservation_id))
   payment=funds['capture_minor'] if funds else a.amount_minor if a.state=='CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED' else 0
   refunded=funds['refund_minor'] if funds else 0
   payload={'state':a.state,'payment':payment,'refund':refunded,'settlement':0};r=AlipayReconciliationRow(reconciliation_id=ident('arec'),authorization_id=authorization_id,authorization_state=a.state,payment_amount_minor=payment,refund_amount_minor=refunded,settlement_amount_minor=0,decision='CONTRACT_ONLY_NOT_EXTERNAL_RECONCILED',evidence_hash=digest(payload),created_at=now());s.add(r);s.commit();return out(r)
 def _event(self,s,aid,typ,payload,verified,external,event_id=None):
  r=AlipaySafeguardedEventRow(safeguarded_event_id=ident('ase'),authorization_id=aid,event_type=typ,source='ALIPAY_CALLBACK' if external else 'GO_CONTRACT',external_event_id=event_id,payload_hash=digest(payload),signature_verified=verified,external_invoked=external,occurred_at=now());s.add(r);return r
alipay_safeguarded_settlement_service=Service()
