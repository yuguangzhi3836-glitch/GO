import hashlib,json
from go_hotel.services.hosted_reservation_operations import managed_session
from datetime import date
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectRoomOfferRow,HostedDirectReservationRow,HostedDirectInventoryPoolRow,HostedInventoryDayRow,HostedReservationStayRow,HostedReservationNightRow,HostedStaffRoleRow,HostedShiftHandoverRow,HostedSlaEscalationRow,HostedActionApprovalRow,HostedDailyCloseRow,HostedUatScenarioRow,HostedGuestAccessAuditRow
from go_hotel.services.hosted_direct_booking import ident,now,out
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
ROLES={'FRONT_DESK','RESERVATIONS','DUTY_MANAGER'}
UAT={'GO_PAGE_BOOKING','PHONE_BOOKING','CONFIRM','REJECT','CANCEL','RESCHEDULE','TIMEOUT_RELEASE','DAILY_CLOSE'}
def masked(v):return (v[:3]+'****'+v[-2:]) if len(v)>6 else '***'
class Service:
 def assign_role(self,hotel_id,b,actor):
  from go_hotel.services.hosted_operation_authority import scoped, user_checked, binding_hash
  from go_hotel.autonomy.durable import transaction
  if b.get('role') not in ROLES or not b.get('staff_id') or not b.get('evidence_reference'):raise ValueError('VALID_STAFF_ROLE_EVIDENCE_REQUIRED')
  if set(b)-{'role','staff_id','evidence_reference'}:raise ValueError('VALID_STAFF_ROLE_EVIDENCE_REQUIRED')
  with transaction(SessionLocal) as s:
   grant=scoped(s,actor,hotel_id,'admin:rules',root_only=True)
   if b['staff_id']==actor.user_id:raise PermissionError('HOSTED_SELF_GRANT_FORBIDDEN')
   user_checked(s,b['staff_id'],'admin:orders')
   proof=json.dumps({'schema':'HOSTED_STAFF_V1','grant_id':grant.staff_role_id,'grant_hash':binding_hash(grant),'reference':b['evidence_reference']},sort_keys=True,separators=(',',':'))
   if len(proof)>512:raise ValueError('STAFF_AUTHORITY_REFERENCE_TOO_LONG')
   r=s.scalar(select(HostedStaffRoleRow).where(HostedStaffRoleRow.hosted_hotel_id==hotel_id,HostedStaffRoleRow.staff_id==b['staff_id'],HostedStaffRoleRow.role==b['role']).with_for_update())
   if r:
    if r.state=='ACTIVE' and r.evidence_reference==proof:return out(r)
    raise ValueError('STAFF_ROLE_ALREADY_EXISTS_REVIEW_REQUIRED')
   r=HostedStaffRoleRow(staff_role_id=ident('hsr'),hosted_hotel_id=hotel_id,staff_id=b['staff_id'],role=b['role'],state='ACTIVE',evidence_reference=proof,created_at=now());s.add(r);s.flush();return out(r)
 def _role(self,s,hotel_id,staff_id,allowed):
  r=s.scalar(select(HostedStaffRoleRow).where(HostedStaffRoleRow.hosted_hotel_id==hotel_id,HostedStaffRoleRow.staff_id==staff_id,HostedStaffRoleRow.role.in_(allowed),HostedStaffRoleRow.state=='ACTIVE'))
  if not r:raise ValueError('HOTEL_STAFF_ROLE_REQUIRED')
  from go_hotel.services.hosted_operation_authority import valid_staff
  return valid_staff(s,r)
 def handover(self,hotel_id,b,actor):
  with SessionLocal() as s:
   self._role(s,hotel_id,actor,ROLES);self._role(s,hotel_id,b['incoming_staff_id'],ROLES)
   offer_ids=[x for x in s.scalars(select(HostedDirectRoomOfferRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id==hotel_id)).all()];unresolved=[x for x in s.scalars(select(HostedDirectReservationRow.hosted_reservation_id).where(HostedDirectReservationRow.hosted_offer_id.in_(offer_ids),HostedDirectReservationRow.reservation_state=='PENDING_HOTEL_CONFIRMATION')).all()] if offer_ids else []
   r=HostedShiftHandoverRow(handover_id=ident('hsh'),hosted_hotel_id=hotel_id,outgoing_staff_id=actor,incoming_staff_id=b['incoming_staff_id'],unresolved_reservation_ids_json=unresolved,notes=b.get('notes',''),state='ACCEPTED',accepted_at=now(),created_at=now());s.add(r);s.commit();return out(r)
 def guest_view(self,reservation_id,b,actor):
  if not b.get('reason'):raise ValueError('GUEST_ACCESS_REASON_REQUIRED')
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id)
   if not r:raise ValueError('RESERVATION_NOT_FOUND')
   offer=s.get(HostedDirectRoomOfferRow,r.hosted_offer_id);role=self._role(s,offer.hosted_hotel_id,actor,ROLES);unmask=bool(b.get('unmask')) and role=='DUTY_MANAGER'
   s.add(HostedGuestAccessAuditRow(guest_access_audit_id=ident('hgaa'),hosted_reservation_id=reservation_id,staff_id=actor,access_mode='UNMASKED' if unmask else 'MASKED',reason=b['reason'],occurred_at=now()));s.commit();return {'guest_name':r.guest_name if unmask else masked(r.guest_name),'guest_contact':r.guest_contact if unmask else masked(r.guest_contact),'access_mode':'UNMASKED' if unmask else 'MASKED'}
 def phone_reserve(self,slug,b,key,actor):
  with managed_session() as s:
   h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==slug).with_for_update());self._role(s,h.hosted_hotel_id,actor,{'FRONT_DESK','RESERVATIONS'})
   old=s.scalar(select(HostedDirectReservationRow).where(HostedDirectReservationRow.idempotency_key==key))
   if old:return ops.reserve(slug,b,key,'PHONE',actor,_session=s)
   duplicate=s.scalar(select(HostedDirectReservationRow).where(HostedDirectReservationRow.hosted_offer_id==b['hosted_offer_id'],HostedDirectReservationRow.guest_contact==b['guest_contact'],HostedDirectReservationRow.check_in==b['check_in'],HostedDirectReservationRow.check_out==b['check_out']))
   if duplicate and not b.get('duplicate_review_evidence'):raise ValueError('POSSIBLE_DUPLICATE_REQUIRES_REVIEW')
   result=ops.reserve(slug,b,key,'PHONE',actor,_session=s);s.commit();return result
 def request_action(self,reservation_id,b,actor):
  if b.get('action_type') not in ('REJECT','CANCEL','RESCHEDULE'):raise ValueError('GOVERNED_ACTION_REQUIRED')
  from copy import deepcopy
  with managed_session() as s:
   r=s.get(HostedDirectReservationRow,reservation_id,with_for_update=True)
   if not r:raise ValueError('RESERVATION_NOT_FOUND')
   offer=s.get(HostedDirectRoomOfferRow,r.hosted_offer_id);self._role(s,offer.hosted_hotel_id,actor,ROLES)
   payload=deepcopy(b.get('payload',{}))
   allowed={'check_in','check_out'} if b['action_type']=='RESCHEDULE' else set()
   if not isinstance(payload,dict) or set(payload)-allowed:raise ValueError('ACTION_PAYLOAD_INVALID')
   if b['action_type']=='RESCHEDULE' and set(payload)!=allowed:raise ValueError('VALID_STAY_DATES_REQUIRED')
   expected={k:getattr(r,k) for k in ('check_in','check_out','amount_minor','currency','reservation_state')}
   payload['_expected_reservation']=expected
   a=HostedActionApprovalRow(action_approval_id=ident('haa'),hosted_reservation_id=reservation_id,action_type=b['action_type'],action_payload_json=payload,requester_id=actor,checker_id=None,evidence_reference=None,state='PENDING_CHECKER',created_at=now());s.add(a);s.commit();return out(a)
 def approve_action(self,approval_id,b,actor):
  from copy import deepcopy
  from go_hotel.core.faults import faults
  if not isinstance(b.get('evidence_reference'),str) or not 1<=len(b['evidence_reference'])<=512:raise ValueError('CHECKER_EVIDENCE_REQUIRED')
  if set(b)-{'evidence_reference'}:raise ValueError('CHECKER_FIELDS_INVALID')
  # Persist the authorization separately, but never call it successful execution.
  with managed_session() as s:
   a=s.get(HostedActionApprovalRow,approval_id,with_for_update=True)
   if not a:raise ValueError('ACTION_APPROVAL_NOT_FOUND')
   if a.requester_id==actor:raise ValueError('MAKER_CHECKER_SEPARATION_REQUIRED')
   r=s.get(HostedDirectReservationRow,a.hosted_reservation_id)
   offer=s.get(HostedDirectRoomOfferRow,r.hosted_offer_id);self._role(s,offer.hosted_hotel_id,actor,{'DUTY_MANAGER'})
   if a.state!='PENDING_CHECKER' and (a.checker_id!=actor or a.evidence_reference!=b['evidence_reference']):raise ValueError('ACTION_APPROVAL_RETRY_BINDING_MISMATCH')
   if a.state=='APPROVED_EXECUTED':
    result=a.action_payload_json.get('_execution_result')
    if result is None:raise ValueError('LEGACY_ACTION_EXECUTION_UNVERIFIED')
    return {'approval':out(a),'reservation':result,'payment_live':False,'replayed':True}
   if a.state not in ('PENDING_CHECKER','APPROVED_PENDING_EXECUTION','APPROVED_RETRY_REQUIRED'):raise ValueError('ACTION_APPROVAL_NOT_PENDING')
   if a.state=='PENDING_CHECKER':
    a.checker_id=actor;a.evidence_reference=b['evidence_reference'];a.state='APPROVED_PENDING_EXECUTION';s.commit()
  faults.hit('hosted_action_after_approval_commit')
  try:
   with managed_session() as s:
    a=s.get(HostedActionApprovalRow,approval_id,with_for_update=True)
    r=s.get(HostedDirectReservationRow,a.hosted_reservation_id,with_for_update=True)
    offer=s.get(HostedDirectRoomOfferRow,r.hosted_offer_id);self._role(s,offer.hosted_hotel_id,actor,{'DUTY_MANAGER'})
    if a.checker_id!=actor or a.evidence_reference!=b['evidence_reference']:raise ValueError('ACTION_APPROVAL_RETRY_BINDING_MISMATCH')
    if a.state=='APPROVED_EXECUTED':return {'approval':out(a),'reservation':a.action_payload_json['_execution_result'],'payment_live':False,'replayed':True}
    if a.state not in ('APPROVED_PENDING_EXECUTION','APPROVED_RETRY_REQUIRED'):raise ValueError('ACTION_APPROVAL_NOT_PENDING')
    payload=deepcopy(a.action_payload_json);expected=payload.pop('_expected_reservation',None);payload.pop('_last_error',None)
    if not expected or any(getattr(r,k)!=v for k,v in expected.items()):raise ValueError('ACTION_RESERVATION_CHANGED_REVIEW_REQUIRED')
    if a.action_type=='RESCHEDULE':result=ops.reschedule(a.hosted_reservation_id,payload,actor,_session=s)
    else:result=ops.action(a.hosted_reservation_id,{'action':a.action_type},actor,_session=s)
    faults.hit('hosted_action_before_execution_commit')
    a.state='APPROVED_EXECUTED';a.action_payload_json={**a.action_payload_json,'_execution_result':result};s.commit()
    return {'approval':out(a),'reservation':result,'payment_live':False}
  except (ValueError,RuntimeError) as exc:
   with managed_session() as s:
    a=s.get(HostedActionApprovalRow,approval_id,with_for_update=True)
    if a and a.state in ('APPROVED_PENDING_EXECUTION','APPROVED_RETRY_REQUIRED'):
     a.state='APPROVED_RETRY_REQUIRED';a.action_payload_json={**a.action_payload_json,'_last_error':str(exc)[:128]};s.commit()
   raise
 def escalate(self,hotel_id,actor):
  with SessionLocal() as s:
   self._role(s,hotel_id,actor,{'FRONT_DESK','RESERVATIONS','DUTY_MANAGER'});manager=s.scalar(select(HostedStaffRoleRow).where(HostedStaffRoleRow.hosted_hotel_id==hotel_id,HostedStaffRoleRow.role=='DUTY_MANAGER',HostedStaffRoleRow.state=='ACTIVE'))
   if not manager:raise ValueError('DUTY_MANAGER_REQUIRED')
   offer_ids=list(s.scalars(select(HostedDirectRoomOfferRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id==hotel_id)).all());stays=s.scalars(select(HostedReservationStayRow).join(HostedDirectReservationRow,HostedDirectReservationRow.hosted_reservation_id==HostedReservationStayRow.hosted_reservation_id).where(HostedDirectReservationRow.hosted_offer_id.in_(offer_ids),HostedReservationStayRow.operational_state=='PENDING_HOTEL_CONFIRMATION')).all() if offer_ids else [];created=0
   for stay in stays:
    if not s.scalar(select(HostedSlaEscalationRow).where(HostedSlaEscalationRow.hosted_reservation_id==stay.hosted_reservation_id,HostedSlaEscalationRow.state=='OPEN')):s.add(HostedSlaEscalationRow(escalation_id=ident('hse'),hosted_reservation_id=stay.hosted_reservation_id,escalation_level='DUTY_MANAGER',manager_staff_id=manager.staff_id,state='OPEN',reason='PENDING_HOTEL_CONFIRMATION_SLA',created_at=now()));created+=1
   s.commit();return {'escalations_created':created,'manager_alert_state':'QUEUED_NOT_SENT','payment_live':False}
 def voucher(self,reservation_id,actor):
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id);offer=s.get(HostedDirectRoomOfferRow,r.hosted_offer_id);self._role(s,offer.hosted_hotel_id,actor,ROLES);nights=s.query(HostedReservationNightRow).filter_by(hosted_reservation_id=reservation_id).count();return {'voucher_type':'ARRIVAL_CONFIRMATION','printable':True,'reservation_id':reservation_id,'guest_name':masked(r.guest_name),'room_name':offer.room_name,'check_in':r.check_in,'check_out':r.check_out,'nights':nights,'amount_minor':r.amount_minor,'payment_state':r.payment_state,'payment_captured':False}
 def daily_close(self,hotel_id,b,actor):
  from go_hotel.services.hosted_business_day import close
  return close(hotel_id,b,actor,self._role)
 def uat(self,hotel_id,b,actor):
  if b.get('scenario_key') not in UAT or b.get('result')!='PASS' or not b.get('evidence_reference'):raise ValueError('VALID_UAT_PASS_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   self._role(s,hotel_id,actor,{'DUTY_MANAGER'});r=HostedUatScenarioRow(uat_scenario_id=ident('huat'),hosted_hotel_id=hotel_id,scenario_key=b['scenario_key'],result='PASS',evidence_reference=b['evidence_reference'],signed_by=actor,executed_at=now());s.add(r);s.commit();count=s.scalar(select(func.count(func.distinct(HostedUatScenarioRow.scenario_key))).where(HostedUatScenarioRow.hosted_hotel_id==hotel_id,HostedUatScenarioRow.result=='PASS'));return {'scenario':out(r),'required_scenarios':sorted(UAT),'operations_uat_complete':count>=len(UAT),'payment_live':False,'production_live':False}
 def dashboard(self,hotel_id):
  with SessionLocal() as s:
   ids=select(HostedDirectReservationRow.hosted_reservation_id).join(HostedDirectRoomOfferRow,HostedDirectRoomOfferRow.hosted_offer_id==HostedDirectReservationRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id==hotel_id)
   return {'active_staff_roles':s.query(HostedStaffRoleRow).filter(HostedStaffRoleRow.hosted_hotel_id==hotel_id,HostedStaffRoleRow.state=='ACTIVE',HostedStaffRoleRow.role.in_(ROLES)).count(),
    'open_sla_escalations':s.query(HostedSlaEscalationRow).filter(HostedSlaEscalationRow.hosted_reservation_id.in_(ids),HostedSlaEscalationRow.state=='OPEN').count(),
    'pending_checker_actions':s.query(HostedActionApprovalRow).filter(HostedActionApprovalRow.hosted_reservation_id.in_(ids),HostedActionApprovalRow.state.in_(['PENDING_CHECKER','APPROVED_PENDING_EXECUTION','APPROVED_RETRY_REQUIRED'])).count(),
    'daily_closes':s.query(HostedDailyCloseRow).filter_by(hosted_hotel_id=hotel_id).count(),
    'uat_passed':s.query(HostedUatScenarioRow).filter_by(hosted_hotel_id=hotel_id,result='PASS').count(),
    'alipay_state':'SANDBOX_APPLICATION_NOT_CREATED','payment_live':False,'production_live':False}
hosted_frontdesk_uat_service=Service()
