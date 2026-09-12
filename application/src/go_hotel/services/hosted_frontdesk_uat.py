import hashlib,json
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
  if b.get('role') not in ROLES or not b.get('staff_id') or not b.get('evidence_reference'):raise ValueError('VALID_STAFF_ROLE_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   if not s.get(HostedDirectHotelRow,hotel_id):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   r=HostedStaffRoleRow(staff_role_id=ident('hsr'),hosted_hotel_id=hotel_id,staff_id=b['staff_id'],role=b['role'],state='ACTIVE',evidence_reference=b['evidence_reference'],created_at=now());s.add(r);s.commit();return out(r)
 def _role(self,s,hotel_id,staff_id,allowed):
  r=s.scalar(select(HostedStaffRoleRow).where(HostedStaffRoleRow.hosted_hotel_id==hotel_id,HostedStaffRoleRow.staff_id==staff_id,HostedStaffRoleRow.role.in_(allowed),HostedStaffRoleRow.state=='ACTIVE'))
  if not r:raise ValueError('HOTEL_STAFF_ROLE_REQUIRED')
  return r.role
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
  with SessionLocal() as s:
   h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==slug));self._role(s,h.hosted_hotel_id,actor,{'FRONT_DESK','RESERVATIONS'})
   duplicate=s.scalar(select(HostedDirectReservationRow).where(HostedDirectReservationRow.hosted_offer_id==b['hosted_offer_id'],HostedDirectReservationRow.guest_contact==b['guest_contact'],HostedDirectReservationRow.check_in==b['check_in'],HostedDirectReservationRow.check_out==b['check_out']))
   if duplicate and not b.get('duplicate_review_evidence'):raise ValueError('POSSIBLE_DUPLICATE_REQUIRES_REVIEW')
  return ops.reserve(slug,b,key,'PHONE',actor)
 def request_action(self,reservation_id,b,actor):
  if b.get('action_type') not in ('REJECT','CANCEL','RESCHEDULE'):raise ValueError('GOVERNED_ACTION_REQUIRED')
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id);offer=s.get(HostedDirectRoomOfferRow,r.hosted_offer_id);self._role(s,offer.hosted_hotel_id,actor,{'FRONT_DESK','RESERVATIONS','DUTY_MANAGER'})
   a=HostedActionApprovalRow(action_approval_id=ident('haa'),hosted_reservation_id=reservation_id,action_type=b['action_type'],action_payload_json=b.get('payload',{}),requester_id=actor,checker_id=None,evidence_reference=None,state='PENDING_CHECKER',created_at=now());s.add(a);s.commit();return out(a)
 def approve_action(self,approval_id,b,actor):
  if not b.get('evidence_reference'):raise ValueError('CHECKER_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   a=s.get(HostedActionApprovalRow,approval_id)
   if not a or a.state!='PENDING_CHECKER':raise ValueError('ACTION_APPROVAL_NOT_PENDING')
   if a.requester_id==actor:raise ValueError('MAKER_CHECKER_SEPARATION_REQUIRED')
   r=s.get(HostedDirectReservationRow,a.hosted_reservation_id);offer=s.get(HostedDirectRoomOfferRow,r.hosted_offer_id);self._role(s,offer.hosted_hotel_id,actor,{'DUTY_MANAGER'});a.checker_id=actor;a.evidence_reference=b['evidence_reference'];a.state='APPROVED_EXECUTED';s.commit()
  if a.action_type=='RESCHEDULE':result=ops.reschedule(a.hosted_reservation_id,a.action_payload_json,actor)
  else:result=ops.action(a.hosted_reservation_id,{'action':a.action_type},actor)
  return {'approval':out(a),'reservation':result,'payment_live':False}
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
  business_date=b.get('business_date') or date.today().isoformat()
  with SessionLocal() as s:
   self._role(s,hotel_id,actor,{'DUTY_MANAGER'});old=s.scalar(select(HostedDailyCloseRow).where(HostedDailyCloseRow.hosted_hotel_id==hotel_id,HostedDailyCloseRow.business_date==business_date))
   if old:return out(old)
   pool_ids=list(s.scalars(select(HostedDirectInventoryPoolRow.inventory_pool_id).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)).all());days=s.scalars(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id.in_(pool_ids),HostedInventoryDayRow.stay_date==business_date)).all() if pool_ids else [];offer_ids=list(s.scalars(select(HostedDirectRoomOfferRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id==hotel_id)).all());rows=s.scalars(select(HostedDirectReservationRow).where(HostedDirectReservationRow.hosted_offer_id.in_(offer_ids))).all() if offer_ids else [];states={k:sum(x.reservation_state==k for x in rows) for k in sorted({x.reservation_state for x in rows})};inv={'total':sum(x.capacity_total for x in days),'available':sum(x.capacity_available for x in days)};exc={'pending':states.get('PENDING_HOTEL_CONFIRMATION',0),'payment_transactions':0,'refund_transactions':0};payload={'inventory':inv,'reservations':states,'exceptions':exc};digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest();r=HostedDailyCloseRow(daily_close_id=ident('hdc'),hosted_hotel_id=hotel_id,business_date=business_date,inventory_snapshot_json=inv,reservation_summary_json=states,exception_summary_json=exc,closed_by=actor,evidence_hash=digest,closed_at=now());s.add(r);s.commit();return out(r)
 def uat(self,hotel_id,b,actor):
  if b.get('scenario_key') not in UAT or b.get('result')!='PASS' or not b.get('evidence_reference'):raise ValueError('VALID_UAT_PASS_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   self._role(s,hotel_id,actor,{'DUTY_MANAGER'});r=HostedUatScenarioRow(uat_scenario_id=ident('huat'),hosted_hotel_id=hotel_id,scenario_key=b['scenario_key'],result='PASS',evidence_reference=b['evidence_reference'],signed_by=actor,executed_at=now());s.add(r);s.commit();count=s.scalar(select(func.count(func.distinct(HostedUatScenarioRow.scenario_key))).where(HostedUatScenarioRow.hosted_hotel_id==hotel_id,HostedUatScenarioRow.result=='PASS'));return {'scenario':out(r),'required_scenarios':sorted(UAT),'operations_uat_complete':count>=len(UAT),'payment_live':False,'production_live':False}
 def dashboard(self,hotel_id):
  with SessionLocal() as s:return {'active_staff_roles':s.query(HostedStaffRoleRow).filter_by(hosted_hotel_id=hotel_id,state='ACTIVE').count(),'open_sla_escalations':s.query(HostedSlaEscalationRow).filter_by(state='OPEN').count(),'pending_checker_actions':s.query(HostedActionApprovalRow).filter_by(state='PENDING_CHECKER').count(),'daily_closes':s.query(HostedDailyCloseRow).filter_by(hosted_hotel_id=hotel_id).count(),'uat_passed':s.query(HostedUatScenarioRow).filter_by(hosted_hotel_id=hotel_id,result='PASS').count(),'alipay_state':'SANDBOX_APPLICATION_NOT_CREATED','payment_live':False,'production_live':False}
hosted_frontdesk_uat_service=Service()
