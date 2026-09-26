from fastapi import APIRouter,Depends,HTTPException,Header,Query
from pydantic import BaseModel,StrictInt
from go_hotel.security.deps import admin_principal,consumer_principal,require_permission
from go_hotel.security.service import Principal
from go_hotel.services.hosted_operation_authority import hosted_admin, mask_operation_result
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as svc
from go_hotel.services.aoluguya_inventory import configure_aoluguya
from go_hotel.services.hosted_content_acceptance import hosted_content_acceptance_service as content_svc
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops_svc
from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as fd_svc
from go_hotel.services.alipay_safeguarded_settlement import alipay_safeguarded_settlement_service as pay_svc
from go_hotel.services.guest_stay_fulfillment import guest_stay_fulfillment_service as stay_svc
from go_hotel.services.post_stay_dispute import post_stay_dispute_service as dispute_svc
from go_hotel.services.booking_data_release import release_booking_data
router=APIRouter(tags=['go-hosted-direct-booking-pilot'])
class Payload(BaseModel):model_config={'extra':'allow'}
def call_admin(fn,*a):
 return mask_operation_result(call(fn,*a))
def call(fn,*a):
 try:return {'data':fn(*a)}
 except PermissionError as e:raise HTTPException(403,detail=str(e))
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/v1/direct/{slug}')
def page(slug:str):return call(svc.page,slug)
@router.post('/v1/direct/{slug}/reservations')
def reserve(slug:str,b:Payload,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(consumer_principal)):
 def execute():
  body=b.model_dump(exclude_none=True)
  if body.get('traveler_id'):
   released=release_booking_data(p.user_id,'HOTEL',[body['traveler_id']],[],requester_id=p.user_id)
   body.update(guest_name=released['items'][0]['full_name'],guest_contact=released['items'][0]['mobile'],profile_release_ids=released['release_ids'])
  return ops_svc.reserve(slug,body,idempotency_key,'GO_PAGE',p.user_id)
 return call(execute)
@router.get('/v1/direct/reservations/{reservation_id}')
def status(reservation_id:str,p:Principal=Depends(consumer_principal)):
 from go_hotel.db.models import HostedReservationStayRow
 from go_hotel.db.session import SessionLocal
 with SessionLocal() as s:
  stay=s.get(HostedReservationStayRow,reservation_id)
  if not stay or stay.created_by!=p.user_id:raise HTTPException(404,detail='RESERVATION_NOT_FOUND')
 data=svc.status(reservation_id)
 from go_hotel.services.hosted_checkout import authorization_summary
 from go_hotel.db.models import HostedDirectReservationRow
 from go_hotel.services.hosted_after_sales import status as after_sales_status
 with SessionLocal() as s:
  data['authorizations']=authorization_summary(s,s.get(HostedDirectReservationRow,reservation_id))
  data['after_sales']=after_sales_status(s,p.user_id,reservation_id)
 return {'data':data}
@router.post('/v1/direct/reservations/{reservation_id}/cancel')
def cancel_own_pending(reservation_id:str,p:Principal=Depends(consumer_principal)):
 return call(ops_svc.action,reservation_id,{'action':'CANCEL'},p.user_id,p.user_id,True,True)
@router.get('/v1/direct/{slug}/catalog')
def catalog(slug:str):
 if slug!='aoluguya-harbin':raise HTTPException(404,detail='HOTEL_NOT_FOUND')
 from go_hotel.services.official_hotel_catalog import official_catalog
 return {'data':official_catalog()}
@router.post('/v1/direct/{slug}/availability')
def availability(slug:str,b:Payload):return call(ops_svc.availability,slug,b.model_dump(exclude_none=True))
@router.get('/internal/v1/hosted-direct/dashboard')
def dashboard(p:Principal=Depends(hosted_admin)):return {'data':svc.dashboard()}
@router.post('/internal/v1/hosted-direct/aoluguya/configure')
def configure(p:Principal=Depends(hosted_admin)):return call_admin(configure_aoluguya)
@router.post('/internal/v1/hosted-direct/hotels')
def hotel(b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(svc.create_hotel,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/offers')
def offer(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(svc.upsert_offer,hotel_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/publish')
def publish(hotel_id:str,p:Principal=Depends(hosted_admin)):return call_admin(svc.publish,hotel_id,p)
@router.post('/internal/v1/hosted-direct/reservations/{reservation_id}/decision')
def decision(reservation_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(svc.hotel_decision,reservation_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/reservations/{reservation_id}/cancel')
def cancel(reservation_id:str,p:Principal=Depends(hosted_admin)):return call_admin(svc.cancel,reservation_id,p.user_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/content-snapshots')
def content_snapshot(hotel_id:str,p:Principal=Depends(require_permission('admin:rules'))):return call_admin(content_svc.snapshot,hotel_id,p)
@router.post('/internal/v1/hosted-direct/content-snapshots/{snapshot_id}/approve')
def content_approve(snapshot_id:str,b:Payload,p:Principal=Depends(require_permission('admin:approve'))):return call_admin(content_svc.approve,snapshot_id,b.model_dump(exclude_none=True),p)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/media-assets')
def media_asset(hotel_id:str,b:Payload,p:Principal=Depends(require_permission('admin:rules'))):return call_admin(content_svc.media,hotel_id,b.model_dump(exclude_none=True),p)
@router.get('/internal/v1/hosted-direct/hotels/{hotel_id}/operations-gate')
def operations_gate(hotel_id:str,p:Principal=Depends(hosted_admin)):return call_admin(content_svc.gate,hotel_id)
@router.post('/v1/direct/{slug}/managed-reservations')
def managed_reserve(slug:str,b:Payload,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(consumer_principal)):return call(ops_svc.reserve,slug,b.model_dump(exclude_none=True),idempotency_key,'GO_PAGE',p.user_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/calendar/bootstrap')
def calendar_bootstrap(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.bootstrap_calendar,hotel_id,b.model_dump(exclude_none=True),p)
@router.put('/internal/v1/hosted-direct/inventory-pools/{pool_id}/days/{stay_date}')
def inventory_day(pool_id:str,stay_date:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.set_inventory_day,pool_id,stay_date,b.model_dump(exclude_none=True),p)
@router.put('/internal/v1/hosted-direct/rate-variants/{variant_id}/days/{stay_date}')
def rate_day(variant_id:str,stay_date:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.set_rate_day,variant_id,stay_date,b.model_dump(exclude_none=True),p)
@router.post('/internal/v1/hosted-direct/{slug}/phone-reservations')
def phone_reserve(slug:str,b:Payload,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.reserve,slug,b.model_dump(exclude_none=True),idempotency_key,'PHONE',p.user_id)
@router.post('/internal/v1/hosted-direct/managed-reservations/{reservation_id}/actions')
def managed_action(reservation_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.action,reservation_id,b.model_dump(exclude_none=True),p)
@router.post('/internal/v1/hosted-direct/managed-reservations/{reservation_id}/reschedule')
def managed_reschedule(reservation_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.reschedule,reservation_id,b.model_dump(exclude_none=True),p)
@router.post('/internal/v1/hosted-direct/managed-reservations/expire-pending')
def expire_pending(p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.expire_pending,p.user_id)
@router.get('/internal/v1/hosted-direct/hotels/{hotel_id}/operations-dashboard')
def operations_dashboard(hotel_id:str,p:Principal=Depends(hosted_admin)):return call_admin(ops_svc.dashboard,hotel_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/staff-roles')
def staff_role(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.assign_role,hotel_id,b.model_dump(exclude_none=True),p)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/shift-handovers')
def shift_handover(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.handover,hotel_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/reservations/{reservation_id}/guest-access')
def guest_access(reservation_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call(fd_svc.guest_view,reservation_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/{slug}/governed-phone-reservations')
def governed_phone(slug:str,b:Payload,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.phone_reserve,slug,b.model_dump(exclude_none=True),idempotency_key,p.user_id)
@router.post('/internal/v1/hosted-direct/reservations/{reservation_id}/action-approvals')
def action_request(reservation_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.request_action,reservation_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/action-approvals/{approval_id}/approve')
def action_approve(approval_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.approve_action,approval_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/sla-escalations/run')
def sla_escalate(hotel_id:str,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.escalate,hotel_id,p.user_id)
@router.get('/internal/v1/hosted-direct/reservations/{reservation_id}/arrival-voucher')
def arrival_voucher(reservation_id:str,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.voucher,reservation_id,p.user_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/daily-closes')
def daily_close(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.daily_close,hotel_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/uat-scenarios')
def uat_scenario(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.uat,hotel_id,b.model_dump(exclude_none=True),p.user_id)
@router.get('/internal/v1/hosted-direct/hotels/{hotel_id}/frontdesk-command-center')
def frontdesk_command_center(hotel_id:str,p:Principal=Depends(hosted_admin)):return call_admin(fd_svc.dashboard,hotel_id)
@router.post('/internal/v1/alipay/hotels/{hotel_id}/merchant-binding')
def alipay_merchant(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.bind_merchant,hotel_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/alipay/merchant-bindings/{binding_id}/credentials')
def alipay_credentials(binding_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.credentials,binding_id,b.model_dump(exclude_none=True))
@router.get('/internal/v1/alipay/hotels/{hotel_id}/activation-gate')
def alipay_gate(hotel_id:str,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.gate,hotel_id)
@router.post('/internal/v1/alipay/reservations/{reservation_id}/authorizations')
def alipay_authorize(reservation_id:str,b:Payload,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.authorize,reservation_id,b.model_dump(exclude_none=True),idempotency_key)
@router.post('/internal/v1/alipay/authorizations/{authorization_id}/release')
def alipay_release(authorization_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.release,authorization_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/alipay/authorizations/{authorization_id}/fulfill')
def alipay_fulfill(authorization_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.fulfill,authorization_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/alipay/authorizations/{authorization_id}/capture')
def alipay_capture(authorization_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.capture,authorization_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/alipay/authorizations/{authorization_id}/adjustments')
def alipay_adjustment(authorization_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.request_adjustment,authorization_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/alipay/adjustments/{approval_id}/approve')
def alipay_adjustment_approve(approval_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.approve_adjustment,approval_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/v1/webhooks/alipay/safeguarded-settlement')
def alipay_webhook(b:Payload,x_alipay_signature:str=Header(alias='X-Alipay-Signature')):return call(pay_svc.webhook,b.model_dump(exclude_none=True),x_alipay_signature)
@router.post('/internal/v1/alipay/authorizations/{authorization_id}/reconcile')
def alipay_reconcile(authorization_id:str,p:Principal=Depends(hosted_admin)):return call_admin(pay_svc.reconcile,authorization_id)


class UnknownFundingEpisodeBody(BaseModel):
 evidence_reference:str
 evidence:dict={}

class ResolveUnknownFundingEpisodeBody(BaseModel):
 decision:str='CONFIRMED'
 expected_open_evidence_digest:str
 evidence_reference:str
 evidence:dict={}

@router.post('/internal/v1/alipay/authorizations/{authorization_id}/funding-movements/{movement_id}/unknown-episodes')
def open_funding_unknown_episode(authorization_id:str,movement_id:str,b:UnknownFundingEpisodeBody,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_money import open_unknown_episode
 return call_admin(open_unknown_episode,authorization_id,movement_id,b.evidence_reference,b.evidence,p.user_id)

@router.post('/internal/v1/alipay/unknown-funding-episodes/{episode_id}/resolve')
def resolve_funding_unknown_episode(episode_id:str,b:ResolveUnknownFundingEpisodeBody,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_money import resolve_unknown_episode
 return call_admin(resolve_unknown_episode,episode_id,b.decision,b.expected_open_evidence_digest,b.evidence_reference,b.evidence,p.user_id)
@router.post('/internal/v1/stays/reservations/{reservation_id}')
def stay_create(reservation_id:str,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.create,reservation_id,p.user_id)
@router.post('/internal/v1/stays/{stay_id}/identity-evidence')
def stay_identity(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.identity,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/stays/{stay_id}/arrive')
def stay_arrive(stay_id:str,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.arrive,stay_id,p.user_id)
@router.post('/internal/v1/stays/{stay_id}/room-assignment')
def stay_room(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.assign_room,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/stays/{stay_id}/check-in')
def stay_checkin(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.check_in,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/stays/{stay_id}/extend')
def stay_extend(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.extend,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/stays/{stay_id}/check-out')
def stay_checkout(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.checkout,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/stays/{stay_id}/no-show')
def stay_noshow(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.no_show,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/stays/{stay_id}/disputes')
def stay_dispute(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.dispute,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/stays/{stay_id}/settlement-eligibility')
def stay_eligibility(stay_id:str,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.eligibility,stay_id)
@router.get('/internal/v1/stays/{stay_id}/timeline')
def stay_timeline(stay_id:str,p:Principal=Depends(hosted_admin)):return call_admin(stay_svc.timeline,stay_id)
@router.post('/internal/v1/post-stay/stays/{stay_id}/cases')
def dispute_open(stay_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.open_case,stay_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/post-stay/cases/{case_id}/evidence')
def dispute_evidence(case_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.evidence,case_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/post-stay/cases/{case_id}/responses')
def dispute_response(case_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.respond,case_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/post-stay/cases/{case_id}/escalate')
def dispute_escalate(case_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.escalate,case_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/post-stay/cases/{case_id}/mediation')
def dispute_mediate(case_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.mediate,case_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/post-stay/cases/{case_id}/decisions')
def dispute_decision(case_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.request_decision,case_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/post-stay/decisions/{decision_id}/approve')
def dispute_decision_approve(decision_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.approve_decision,decision_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/post-stay/decisions/{decision_id}/refund-eligibility')
def refund_eligibility(decision_id:str,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.refund_eligibility,decision_id)
@router.post('/internal/v1/post-stay/refund-eligibilities/{eligibility_id}/execute')
def refund_execute(eligibility_id:str,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.execute_refund,eligibility_id)
@router.post('/internal/v1/post-stay/cases/{case_id}/reconcile')
def dispute_reconcile(case_id:str,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.reconcile,case_id)
@router.post('/internal/v1/post-stay/cases/{case_id}/close')
def dispute_close(case_id:str,b:Payload,p:Principal=Depends(hosted_admin)):return call_admin(dispute_svc.close,case_id,b.model_dump(exclude_none=True),p.user_id)

from go_hotel.api.routes.consumer_checkout import CheckoutConfirmation
@router.post('/v1/direct/reservations/{reservation_id}/checkout')
def direct_checkout(reservation_id:str,b:CheckoutConfirmation,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_checkout import authorize
 return call(authorize,p.user_id,reservation_id,b.expected_amount_minor,b.currency)
@router.get('/v1/consumer/direct-reservations')
def own_direct_reservations(p:Principal=Depends(consumer_principal)):
 from sqlalchemy import select
 from go_hotel.db.models import HostedDirectReservationRow as Reservation,HostedReservationStayRow as Stay
 from go_hotel.db.session import SessionLocal
 with SessionLocal() as s:
  rows=s.scalars(select(Reservation).join(Stay,Stay.hosted_reservation_id==Reservation.hosted_reservation_id)
   .where(Stay.created_by==p.user_id).order_by(Reservation.created_at.desc()).limit(20)).all()
  return {'data':{'items':[{'hosted_reservation_id':r.hosted_reservation_id,'check_in':r.check_in,
   'check_out':r.check_out,'reservation_state':r.reservation_state,'payment_state':r.payment_state,
   'amount_minor':r.amount_minor,'currency':r.currency} for r in rows]}}

class CustomerStayDispute(BaseModel):
 model_config={'extra':'forbid'}
 dispute_type:str
 description:str

@router.post('/v1/direct/reservations/{reservation_id}/cases')
def own_stay_case(reservation_id:str,b:CustomerStayDispute,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_after_sales import open_case
 return call(open_case,p.user_id,reservation_id,b.dispute_type,b.description,idempotency_key)

@router.post('/v1/direct/reservations/{reservation_id}/refunds/{eligibility_id}/retry')
def own_stay_refund_retry(reservation_id:str,eligibility_id:str,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_after_sales import retry_refund
 return call(retry_refund,p.user_id,reservation_id,eligibility_id)


class FareCancellationConfirmation(BaseModel):
 model_config={'extra':'forbid'}
 quote_id:str
 expected_fee_minor:StrictInt
 currency:str

@router.post('/v1/direct/reservations/{reservation_id}/fare/cancellation-quote')
def own_fare_quote(reservation_id:str,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_fare_rules import create_quote
 return call(create_quote,reservation_id,'CANCEL_FOR_REFUND',p.user_id)

@router.post('/v1/direct/reservations/{reservation_id}/fare/cancel')
def own_fare_cancel(reservation_id:str,b:FareCancellationConfirmation,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_fare_rules import execute
 return call(execute,reservation_id,b.quote_id,b.expected_fee_minor,b.currency,p.user_id)

class FarePublication(BaseModel):
 model_config={'extra':'forbid'}
 rules:dict
 authority_reference:str

@router.post('/internal/v1/hosted-direct/offers/{offer_id}/fare-rules')
def publish_fare_rule(offer_id:str,b:FarePublication,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_fare_rules import publish
 return call_admin(publish,offer_id,b.rules,b.authority_reference,p.user_id)

@router.post('/internal/v1/hosted-direct/reservations/{reservation_id}/fare/no-show-quote')
def no_show_fare_quote(reservation_id:str,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_fare_rules import create_quote
 return call_admin(create_quote,reservation_id,'NO_SHOW')

class FareQuoteReference(BaseModel):
 model_config={'extra':'forbid'}
 quote_id:str

@router.post('/internal/v1/hosted-direct/reservations/{reservation_id}/fare/no-show-review')
def no_show_fare_review(reservation_id:str,b:FareQuoteReference,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_fare_rules import request_no_show
 return call_admin(request_no_show,reservation_id,b.quote_id,p.user_id)


class FareDateRequest(BaseModel):
 model_config={'extra':'forbid'}
 action:str
 check_in:str
 check_out:str

class FareDateConfirmation(BaseModel):
 model_config={'extra':'forbid'}
 quote_id:str
 expected_total_minor:StrictInt
 expected_additional_minor:StrictInt
 currency:str

@router.post('/v1/direct/reservations/{reservation_id}/fare/change-quote')
def own_fare_date_quote(reservation_id:str,b:FareDateRequest,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_fare_change import create_quote
 return call(create_quote,reservation_id,p.user_id,b.action,b.check_in,b.check_out)

@router.post('/v1/direct/reservations/{reservation_id}/fare/change')
def own_fare_date_change(reservation_id:str,b:FareDateConfirmation,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_fare_change import execute
 return call(execute,reservation_id,p.user_id,b.quote_id,b.expected_total_minor,b.expected_additional_minor,b.currency)

class CreditConversionConfirmation(BaseModel):
 model_config={'extra':'forbid'}
 quote_id:str
 expected_value_minor:StrictInt
 currency:str

class CreditRedemptionDates(BaseModel):
 model_config={'extra':'forbid'}
 hosted_offer_id:str
 check_in:str
 check_out:str
 adults:StrictInt=1
 children:StrictInt=0

class CreditRedemptionConfirmation(BaseModel):
 model_config={'extra':'forbid'}
 quote_id:str
 expected_due_minor:StrictInt
 currency:str
 traveler_id:str
 consent_id:str

@router.post('/v1/direct/reservations/{reservation_id}/fare/credit-quote')
def own_credit_conversion_quote(reservation_id:str,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_stay_credit import conversion_quote
 return call(conversion_quote,reservation_id,p.user_id)

@router.post('/v1/direct/reservations/{reservation_id}/fare/convert-credit')
def own_credit_conversion(reservation_id:str,b:CreditConversionConfirmation,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_stay_credit import convert
 return call(convert,reservation_id,p.user_id,b.quote_id,b.expected_value_minor,b.currency)

@router.get('/v1/consumer/stay-credits')
def own_stay_credits(p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_stay_credit import list_credits
 return {'data':{'items':list_credits(p.user_id)}}

@router.post('/v1/consumer/stay-credits/{credit_id}/quote')
def own_credit_redemption_quote(credit_id:str,b:CreditRedemptionDates,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.hosted_stay_credit import redemption_quote
 return call(redemption_quote,credit_id,p.user_id,b.hosted_offer_id,b.check_in,b.check_out,b.adults,b.children)

@router.post('/v1/consumer/stay-credits/{credit_id}/redeem')
def own_credit_redemption(credit_id:str,b:CreditRedemptionConfirmation,p:Principal=Depends(consumer_principal)):
 def execute():
  from go_hotel.db.session import SessionLocal
  from go_hotel.services.hosted_credit_value import checked
  from go_hotel.services.hosted_stay_credit import redeem,booking_consent
  with SessionLocal() as s:
   checked(s,credit_id,p.user_id);booking_consent(s,p.user_id,b.traveler_id,b.consent_id)
  if not b.traveler_id.strip():raise ValueError('VAULT_TRAVELER_REFERENCE_REQUIRED')
  released=release_booking_data(p.user_id,'HOTEL',[b.traveler_id],[],requester_id=p.user_id)
  person=released['items'][0]
  return redeem(credit_id,p.user_id,b.quote_id,b.expected_due_minor,b.currency,person['full_name'],person['mobile'],
    {'traveler_id':b.traveler_id,'consent_id':b.consent_id,'release_ids':released['release_ids']})
 return call(execute)

@router.post('/internal/v1/hosted-direct/stay-credits/expire')
def expire_stay_credits(p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_stay_credit import expire
 return call_admin(expire)

class SupplierDisruptionEvidence(BaseModel):
 model_config={'extra':'forbid'}
 reference:str
 sha256:str
 type:str

class SupplierDisruptionRequest(BaseModel):
 model_config={'extra':'forbid'}
 claimed_cause:str
 evidence:list[SupplierDisruptionEvidence]

class SupplierDisruptionReview(BaseModel):
 model_config={'extra':'forbid'}
 confirmed_cause:str
 accepted_evidence_ids:list[str]
 decision_reference:str
 expected_evidence_hash:str

class SupplierDisruptionExecution(BaseModel):
 model_config={'extra':'forbid'}
 expected_decision_hash:str

class FaultMandateRequest(BaseModel):
 model_config={'extra':'forbid'}
 currency:str
 maximum_per_case_minor:StrictInt
 expires_at:str
 authority_reference:str
 authority_hash:str

class FaultRecoveryRequest(BaseModel):
 model_config={'extra':'forbid'}
 amount_minor:StrictInt
 settlement_reference:str

@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/reservations/{reservation_id}/disruptions')
def request_supplier_disruption(hotel_id:str,reservation_id:str,b:SupplierDisruptionRequest,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_supplier_disruption import request
 return call_admin(request,reservation_id,hotel_id,b.claimed_cause,[x.model_dump() for x in b.evidence],p.user_id,idempotency_key)

@router.get('/internal/v1/hosted-direct/disruptions/{case_id}')
def get_supplier_disruption(case_id:str,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_supplier_disruption import admin_detail
 return call_admin(admin_detail,case_id)

@router.post('/internal/v1/hosted-direct/disruptions/{case_id}/evidence')
def add_supplier_disruption_evidence(case_id:str,b:SupplierDisruptionEvidence,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_supplier_disruption import add_evidence
 return call_admin(add_evidence,case_id,b.model_dump(),p.user_id)

@router.post('/internal/v1/hosted-direct/disruptions/{case_id}/review')
def review_supplier_disruption(case_id:str,b:SupplierDisruptionReview,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_supplier_disruption import review
 return call_admin(review,case_id,b.confirmed_cause,b.accepted_evidence_ids,b.decision_reference,p.user_id,b.expected_evidence_hash)

@router.post('/internal/v1/hosted-direct/disruptions/{case_id}/execute')
def execute_supplier_disruption(case_id:str,b:SupplierDisruptionExecution,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_supplier_disruption import execute
 return call_admin(execute,case_id,b.expected_decision_hash)

@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/fault-mandates')
def create_supplier_fault_mandate(hotel_id:str,b:FaultMandateRequest,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_fault_funding import register_mandate
 return call_admin(register_mandate,hotel_id,b.currency,b.maximum_per_case_minor,b.expires_at,b.authority_reference,b.authority_hash,p.user_id)

@router.post('/internal/v1/hosted-direct/fault-mandates/{mandate_id}/revoke')
def revoke_supplier_fault_mandate(mandate_id:str,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_fault_funding import revoke_mandate
 return call_admin(revoke_mandate,mandate_id,p.user_id)

@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/fault-recoveries')
def supplier_fault_recovery(hotel_id:str,b:FaultRecoveryRequest,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_fault_funding import recover
 return call_admin(recover,hotel_id,b.amount_minor,b.settlement_reference,idempotency_key,p.user_id)

@router.post('/v1/direct/reservations/{reservation_id}/disruption/retry')
def customer_supplier_remedy_retry(reservation_id:str,p:Principal=Depends(consumer_principal)):
 def execute():
  from sqlalchemy import select
  from go_hotel.db.session import SessionLocal
  from go_hotel.db.models import HostedSupplierDisruptionRow
  from go_hotel.services.hosted_supplier_disruption import execute as resume
  with SessionLocal() as s:
   c=s.scalar(select(HostedSupplierDisruptionRow).where(HostedSupplierDisruptionRow.hosted_reservation_id==reservation_id,HostedSupplierDisruptionRow.account_id==p.user_id))
   if not c:raise ValueError('SUPPLIER_DISRUPTION_NOT_FOUND')
   case_id=c.case_id
  return resume(case_id)
 return call(execute)

@router.get('/internal/v1/hosted-direct/disruptions')
def list_supplier_disruptions(offset:int=Query(default=0,ge=0),p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_supplier_disruption import admin_cases
 return {'data':admin_cases(offset)}

@router.get('/internal/v1/hosted-direct/disruption-candidates')
def list_supplier_disruption_candidates(offset:int=Query(default=0,ge=0),p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_supplier_disruption import candidates
 return {'data':candidates(offset)}

@router.get('/internal/v1/hosted-direct/hotels/{hotel_id}/fault-finance')
def supplier_fault_finance(hotel_id:str,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_fault_funding import finance_status
 return call_admin(finance_status,hotel_id)


@router.get('/internal/v1/hosted-direct/hotels/{hotel_id}/publication-preview')
def publication_preview(hotel_id:str,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_publication import preview
 return call_admin(preview,hotel_id,p)

@router.post('/internal/v1/hosted-direct/hotels/{hotel_id}/publication-review')
def publication_review(hotel_id:str,b:Payload,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_publication import review
 return call_admin(review,hotel_id,b.model_dump(exclude_none=True),p)

@router.get('/v1/direct/{slug}/media/{media_id}')
def hosted_original(slug:str,media_id:str):
 from fastapi import Response
 from go_hotel.services.hosted_publication import public_original
 try:
  raw,mime=public_original(slug,media_id)
  return Response(raw,media_type=mime,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
 except (ValueError,PermissionError):raise HTTPException(404,detail='HOSTED_MEDIA_NOT_FOUND') from None

@router.put('/internal/v1/hosted-direct/inventory-pools/{pool_id}/room-registry')
def room_registry(pool_id:str,b:Payload,p:Principal=Depends(hosted_admin)):
 from go_hotel.services.hosted_room_registry import configure_isolated_registry
 return call_admin(configure_isolated_registry,pool_id,b.model_dump(exclude_none=True),p)
