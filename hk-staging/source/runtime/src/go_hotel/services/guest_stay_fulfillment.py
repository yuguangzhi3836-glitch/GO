import hashlib,json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectReservationRow,GuestStayLifecycleRow,GuestIdentityEvidenceRow,GuestStayEventRow,StayFulfillmentEvidenceRow,StayDisputeRow,SettlementEligibilityDecisionRow,AlipayAuthorizationRow,AlipayAdjustmentApprovalRow
from go_hotel.services.hosted_direct_booking import ident,now,out
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
class Service:
 def create(self,reservation_id,actor):
  with SessionLocal() as s:
   old=s.scalar(select(GuestStayLifecycleRow).where(GuestStayLifecycleRow.hosted_reservation_id==reservation_id))
   if old:return out(old)
   r=s.get(HostedDirectReservationRow,reservation_id)
   if not r:raise ValueError('RESERVATION_NOT_FOUND')
   x=GuestStayLifecycleRow(stay_lifecycle_id=ident('gsl'),hosted_reservation_id=reservation_id,state='PRE_ARRIVAL',assigned_room_reference=None,planned_check_out=r.check_out,actual_check_in_at=None,actual_check_out_at=None,updated_at=now());s.add(x);s.flush();self._event(s,x,'PRE_ARRIVAL_CREATED',actor,{});s.commit();return out(x)
 def identity(self,stay_id,b,actor):
  if not b.get('identity_evidence_hash') or len(b['identity_evidence_hash'])!=64 or b.get('verification_method') not in ('HOTEL_DESK_DOCUMENT_CHECK','AUTHORIZED_DIGITAL_ID'):raise ValueError('HASHED_IDENTITY_VERIFICATION_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id)
   if not x:raise ValueError('STAY_NOT_FOUND')
   r=GuestIdentityEvidenceRow(identity_evidence_id=ident('gie'),stay_lifecycle_id=stay_id,evidence_hash=b['identity_evidence_hash'],verification_method=b['verification_method'],verified_by=actor,state='VERIFIED_REFERENCE_ONLY',verified_at=now());s.add(r);self._event(s,x,'IDENTITY_VERIFIED',actor,{'evidence_hash':b['identity_evidence_hash']});s.commit();return out(r)
 def arrive(self,stay_id,actor):
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id)
   if not x or x.state!='PRE_ARRIVAL':raise ValueError('STAY_NOT_PRE_ARRIVAL')
   x.state='ARRIVED';x.updated_at=now();self._event(s,x,'GUEST_ARRIVED',actor,{});s.commit();return out(x)
 def assign_room(self,stay_id,b,actor):
  if not b.get('room_reference'):raise ValueError('ROOM_REFERENCE_REQUIRED')
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id)
   if not x or x.state not in ('ARRIVED','IN_HOUSE'):raise ValueError('ROOM_ASSIGNMENT_STATE_INVALID')
   typ='ROOM_CHANGED' if x.assigned_room_reference else 'ROOM_ASSIGNED';old=x.assigned_room_reference;x.assigned_room_reference=b['room_reference'];x.updated_at=now();self._event(s,x,typ,actor,{'previous':old,'current':x.assigned_room_reference,'evidence_reference':b.get('evidence_reference')});s.commit();return out(x)
 def check_in(self,stay_id,b,actor):
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id);identity=s.scalar(select(GuestIdentityEvidenceRow).where(GuestIdentityEvidenceRow.stay_lifecycle_id==stay_id,GuestIdentityEvidenceRow.state=='VERIFIED_REFERENCE_ONLY'))
   if not x or x.state!='ARRIVED' or not x.assigned_room_reference or not identity or not b.get('registration_evidence_reference'):raise ValueError('IDENTITY_ROOM_AND_REGISTRATION_REQUIRED')
   x.state='IN_HOUSE';x.actual_check_in_at=now();x.updated_at=now();self._event(s,x,'CHECKED_IN',actor,b);s.commit();return out(x)
 def extend(self,stay_id,b,actor):
  if not b.get('new_check_out') or not b.get('inventory_extension_reference'):raise ValueError('EXTENSION_INVENTORY_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id)
   if not x or x.state!='IN_HOUSE' or b['new_check_out']<=x.planned_check_out:raise ValueError('VALID_IN_HOUSE_EXTENSION_REQUIRED')
   old=x.planned_check_out;x.planned_check_out=b['new_check_out'];x.updated_at=now();self._event(s,x,'STAY_EXTENDED',actor,{'from':old,'to':x.planned_check_out,'inventory_reference':b['inventory_extension_reference']});s.commit();return out(x)
 def checkout(self,stay_id,b,actor):
  if not b.get('hotel_fulfillment_evidence') or not b.get('guest_checkout_reference'):raise ValueError('DUAL_FULFILLMENT_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id);reservation=s.get(HostedDirectReservationRow,x.hosted_reservation_id) if x else None;amount=int(b.get('fulfilled_amount_minor',reservation.amount_minor if reservation else 0))
   if not x or x.state!='IN_HOUSE' or amount<0 or amount>reservation.amount_minor:raise ValueError('VALID_IN_HOUSE_CHECKOUT_AMOUNT_REQUIRED')
   x.state='CHECKED_OUT';x.actual_check_out_at=now();x.updated_at=now();f=StayFulfillmentEvidenceRow(fulfillment_evidence_id=ident('sfe'),stay_lifecycle_id=stay_id,hotel_evidence_reference=b['hotel_fulfillment_evidence'],guest_checkout_reference=b['guest_checkout_reference'],fulfilled_amount_minor=amount,state='DUAL_CONFIRMED',confirmed_at=now());s.add(f);self._event(s,x,'CHECKED_OUT_EARLY' if amount<reservation.amount_minor else 'CHECKED_OUT',actor,b);s.commit();return out(x)
 def no_show(self,stay_id,b,actor):
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id);a=s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==x.hosted_reservation_id)) if x else None;approval=s.scalar(select(AlipayAdjustmentApprovalRow).where(AlipayAdjustmentApprovalRow.authorization_id==a.authorization_id,AlipayAdjustmentApprovalRow.adjustment_type=='NO_SHOW',AlipayAdjustmentApprovalRow.state=='APPROVED_CONTRACT_ONLY')) if a else None
   if not x or x.state!='PRE_ARRIVAL' or not approval or not b.get('hotel_no_show_evidence'):raise ValueError('APPROVED_NO_SHOW_EVIDENCE_REQUIRED')
   x.state='NO_SHOW';x.updated_at=now();self._event(s,x,'NO_SHOW_CONFIRMED',actor,{'approval_id':approval.adjustment_approval_id,'evidence':b['hotel_no_show_evidence']});s.commit();return out(x)
 def dispute(self,stay_id,b,actor):
  if b.get('dispute_type') not in ('SERVICE','IDENTITY','AMOUNT','NO_SHOW') or not b.get('evidence_reference'):raise ValueError('VALID_DISPUTE_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id)
   if not x:raise ValueError('STAY_NOT_FOUND')
   r=StayDisputeRow(stay_dispute_id=ident('sdp'),stay_lifecycle_id=stay_id,dispute_type=b['dispute_type'],description=b.get('description',''),evidence_reference=b['evidence_reference'],state='OPEN_SETTLEMENT_FROZEN',opened_at=now());s.add(r);self._event(s,x,'DISPUTE_OPENED',actor,{'dispute_id':r.stay_dispute_id});s.commit();return out(r)
 def eligibility(self,stay_id):
  with SessionLocal() as s:
   x=s.get(GuestStayLifecycleRow,stay_id)
   if not x:raise ValueError('STAY_NOT_FOUND')
   blockers=[];amount=0;open_dispute=s.scalar(select(StayDisputeRow).where(StayDisputeRow.stay_lifecycle_id==stay_id,StayDisputeRow.state=='OPEN_SETTLEMENT_FROZEN'))
   if open_dispute:blockers.append('OPEN_FULFILLMENT_DISPUTE')
   if x.state=='CHECKED_OUT':
    f=s.scalar(select(StayFulfillmentEvidenceRow).where(StayFulfillmentEvidenceRow.stay_lifecycle_id==stay_id,StayFulfillmentEvidenceRow.state=='DUAL_CONFIRMED'))
    if not f:blockers.append('DUAL_FULFILLMENT_EVIDENCE_REQUIRED')
    else:amount=f.fulfilled_amount_minor
   elif x.state=='NO_SHOW':
    a=s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==x.hosted_reservation_id));p=s.scalar(select(AlipayAdjustmentApprovalRow).where(AlipayAdjustmentApprovalRow.authorization_id==a.authorization_id,AlipayAdjustmentApprovalRow.adjustment_type=='NO_SHOW',AlipayAdjustmentApprovalRow.state=='APPROVED_CONTRACT_ONLY')) if a else None
    if not p:blockers.append('APPROVED_NO_SHOW_AMOUNT_REQUIRED')
    else:amount=p.amount_minor
   else:blockers.append('STAY_NOT_COMPLETED')
   decision='ELIGIBLE_CONTRACT_ONLY' if not blockers else 'BLOCKED';payload={'stay':stay_id,'state':x.state,'amount':amount if not blockers else 0,'blockers':blockers};r=SettlementEligibilityDecisionRow(settlement_eligibility_id=ident('sed'),stay_lifecycle_id=stay_id,decision=decision,eligible_amount_minor=amount if not blockers else 0,blockers_json=blockers,evidence_hash=digest(payload),external_payment_invoked=False,decided_at=now());s.add(r);s.commit();return out(r)
 def timeline(self,stay_id):
  with SessionLocal() as s:return {'stay':out(s.get(GuestStayLifecycleRow,stay_id)),'events':[out(x) for x in s.scalars(select(GuestStayEventRow).where(GuestStayEventRow.stay_lifecycle_id==stay_id).order_by(GuestStayEventRow.occurred_at)).all()],'payment_live':False,'production_live':False}
 def _event(self,s,x,typ,actor,payload):s.add(GuestStayEventRow(stay_event_id=ident('gse'),stay_lifecycle_id=x.stay_lifecycle_id,event_type=typ,actor_id=actor,payload_json=payload,evidence_hash=digest({'type':typ,'actor':actor,'payload':payload}),occurred_at=now()))
guest_stay_fulfillment_service=Service()
