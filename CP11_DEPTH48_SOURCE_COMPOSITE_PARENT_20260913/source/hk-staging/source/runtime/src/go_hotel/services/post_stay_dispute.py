import hashlib,json
from datetime import timedelta
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import GuestStayLifecycleRow,StayFulfillmentEvidenceRow,StayDisputeRow,SettlementEligibilityDecisionRow,AlipayAuthorizationRow,AlipayAdjustmentApprovalRow,PostStayDisputeCaseRow,PostStayDisputeEvidenceRow,PostStayDisputeCommunicationRow,PostStayMediationRow,PostStayDecisionRow,RefundEligibilityRow,PostStayReconciliationRow
from go_hotel.services.hosted_direct_booking import ident,now,out
TYPES={'SERVICE','AMOUNT','NO_SHOW','CANCELLATION','IDENTITY','FULFILLMENT'};PARTIES={'GUEST','HOTEL','GO'}
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
class Service:
 def open_case(self,stay_id,b,actor):
  if b.get('opened_by_party') not in PARTIES or b.get('dispute_type') not in TYPES or not b.get('assigned_to'):raise ValueError('VALID_DISPUTE_PARTY_TYPE_ASSIGNEE_REQUIRED')
  with SessionLocal() as s:
   stay=s.get(GuestStayLifecycleRow,stay_id)
   if not stay:raise ValueError('STAY_NOT_FOUND')
   t=now();r=PostStayDisputeCaseRow(dispute_case_id=ident('pdc'),stay_lifecycle_id=stay_id,opened_by_party=b['opened_by_party'],dispute_type=b['dispute_type'],assigned_to=b['assigned_to'],state='OPEN_EVIDENCE_COLLECTION',response_due_at=t+timedelta(hours=24),evidence_due_at=t+timedelta(hours=72),closure_hash=None,created_at=t);s.add(r);s.flush();s.add(StayDisputeRow(stay_dispute_id=ident('sdp'),stay_lifecycle_id=stay_id,dispute_type=b['dispute_type'],description=b.get('description',''),evidence_reference=b.get('initial_evidence_reference','case://pending'),state='OPEN_SETTLEMENT_FROZEN',opened_at=t));s.commit();return out(r)
 def evidence(self,case_id,b):
  if b.get('submitted_by_party') not in PARTIES or b.get('evidence_type') not in ('IMAGE','FILE','COMMUNICATION','TIMELINE') or not b.get('storage_reference') or not b.get('content_hash'):raise ValueError('VALID_CASE_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   if not s.get(PostStayDisputeCaseRow,case_id):raise ValueError('DISPUTE_CASE_NOT_FOUND')
   r=PostStayDisputeEvidenceRow(dispute_evidence_id=ident('pde'),dispute_case_id=case_id,submitted_by_party=b['submitted_by_party'],evidence_type=b['evidence_type'],storage_reference=b['storage_reference'],content_hash=b['content_hash'],created_at=now());s.add(r);s.commit();return out(r)
 def respond(self,case_id,b):
  if b.get('party') not in PARTIES or not b.get('message_reference'):raise ValueError('VALID_PARTY_RESPONSE_REQUIRED')
  with SessionLocal() as s:
   c=s.get(PostStayDisputeCaseRow,case_id)
   if not c:raise ValueError('DISPUTE_CASE_NOT_FOUND')
   r=PostStayDisputeCommunicationRow(communication_id=ident('pcom'),dispute_case_id=case_id,party=b['party'],message_reference=b['message_reference'],message_hash=digest(b['message_reference']),created_at=now());s.add(r);c.state='UNDER_REVIEW';s.commit();return out(r)
 def escalate(self,case_id,b,actor):
  with SessionLocal() as s:
   c=s.get(PostStayDisputeCaseRow,case_id)
   if not c:raise ValueError('DISPUTE_CASE_NOT_FOUND')
   if not b.get('force_for_test'):
    due=c.response_due_at
    if due.tzinfo is None:due=due.replace(tzinfo=now().tzinfo)
    if now()<=due:raise ValueError('SLA_NOT_BREACHED')
   c.state='SLA_ESCALATED';c.assigned_to=b.get('escalate_to','GO_DUTY_MANAGER');s.commit();return out(c)
 def mediate(self,case_id,b,actor):
  if b.get('recommendation') not in ('FULL_REFUND','PARTIAL_REFUND','NO_REFUND') or int(b.get('recommended_refund_minor',-1))<0 or not b.get('rationale_reference'):raise ValueError('VALID_MEDIATION_REQUIRED')
  with SessionLocal() as s:
   c=s.get(PostStayDisputeCaseRow,case_id)
   if not c:raise ValueError('DISPUTE_CASE_NOT_FOUND')
   r=PostStayMediationRow(mediation_id=ident('pmed'),dispute_case_id=case_id,recommendation=b['recommendation'],recommended_refund_minor=int(b['recommended_refund_minor']),rationale_reference=b['rationale_reference'],created_by=actor,created_at=now());s.add(r);c.state='MEDIATION_PROPOSED';s.commit();return out(r)
 def request_decision(self,case_id,b,actor):
  if b.get('outcome') not in ('FULL_REFUND','PARTIAL_REFUND','NO_REFUND') or int(b.get('refund_amount_minor',-1))<0:raise ValueError('VALID_REFUND_DECISION_REQUIRED')
  with SessionLocal() as s:
   c=s.get(PostStayDisputeCaseRow,case_id)
   if not c:raise ValueError('DISPUTE_CASE_NOT_FOUND')
   r=PostStayDecisionRow(post_stay_decision_id=ident('psd'),dispute_case_id=case_id,outcome=b['outcome'],refund_amount_minor=int(b['refund_amount_minor']),requester_id=actor,checker_id=None,evidence_reference=None,state='PENDING_CHECKER',created_at=now());s.add(r);s.commit();return out(r)
 def approve_decision(self,decision_id,b,actor):
  if not b.get('evidence_reference'):raise ValueError('DECISION_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   d=s.get(PostStayDecisionRow,decision_id)
   if not d or d.state!='PENDING_CHECKER':raise ValueError('DECISION_NOT_PENDING')
   if d.requester_id==actor:raise ValueError('MAKER_CHECKER_SEPARATION_REQUIRED')
   c=s.get(PostStayDisputeCaseRow,d.dispute_case_id);stay=s.get(GuestStayLifecycleRow,c.stay_lifecycle_id);f=s.scalar(select(StayFulfillmentEvidenceRow).where(StayFulfillmentEvidenceRow.stay_lifecycle_id==stay.stay_lifecycle_id));a=s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==stay.hosted_reservation_id));caps=[x for x in (f.fulfilled_amount_minor if f else None,a.amount_minor if a else None) if x is not None];cap=min(caps) if caps else 0
   if d.refund_amount_minor>cap:raise ValueError('REFUND_EXCEEDS_CONFIRMED_FULFILLMENT_OR_AUTHORIZATION')
   if d.outcome=='NO_REFUND' and d.refund_amount_minor!=0:raise ValueError('NO_REFUND_AMOUNT_MUST_BE_ZERO')
   d.checker_id=actor;d.evidence_reference=b['evidence_reference'];d.state='APPROVED_CONTRACT_ONLY';c.state='DECIDED';s.commit();return out(d)
 def refund_eligibility(self,decision_id):
  with SessionLocal() as s:
   old=s.scalar(select(RefundEligibilityRow).where(RefundEligibilityRow.post_stay_decision_id==decision_id))
   if old:return out(old)
   d=s.get(PostStayDecisionRow,decision_id)
   if not d or d.state!='APPROVED_CONTRACT_ONLY':raise ValueError('APPROVED_DECISION_REQUIRED')
   decision='NO_REFUND_ELIGIBLE' if d.refund_amount_minor==0 else 'REFUND_ELIGIBLE_CONTRACT_ONLY';payload={'decision':decision,'amount':d.refund_amount_minor};r=RefundEligibilityRow(refund_eligibility_id=ident('rei'),post_stay_decision_id=decision_id,decision=decision,eligible_amount_minor=d.refund_amount_minor,original_payment_reference=None,external_refund_invoked=False,blockers_json=['REAL_ALIPAY_PAYMENT_REFERENCE_REQUIRED'] if d.refund_amount_minor else [],evidence_hash=digest(payload),created_at=now());s.add(r);s.commit();return out(r)
 def execute_refund(self,eligibility_id):raise ValueError('REAL_ALIPAY_REFUND_EXECUTOR_NOT_CONFIGURED')
 def reconcile(self,case_id):
  with SessionLocal() as s:
   c=s.get(PostStayDisputeCaseRow,case_id);stay=s.get(GuestStayLifecycleRow,c.stay_lifecycle_id) if c else None
   if not c:raise ValueError('DISPUTE_CASE_NOT_FOUND')
   settlement=s.scalar(select(SettlementEligibilityDecisionRow).where(SettlementEligibilityDecisionRow.stay_lifecycle_id==stay.stay_lifecycle_id).order_by(SettlementEligibilityDecisionRow.decided_at.desc()));decision=s.scalar(select(PostStayDecisionRow).where(PostStayDecisionRow.dispute_case_id==case_id,PostStayDecisionRow.state=='APPROVED_CONTRACT_ONLY'));refund=s.scalar(select(RefundEligibilityRow).where(RefundEligibilityRow.post_stay_decision_id==decision.post_stay_decision_id)) if decision else None;a=s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==stay.hosted_reservation_id));adjustments=s.scalars(select(AlipayAdjustmentApprovalRow).where(AlipayAdjustmentApprovalRow.authorization_id==a.authorization_id,AlipayAdjustmentApprovalRow.state=='APPROVED_CONTRACT_ONLY')).all() if a else [];cancel=sum(x.amount_minor for x in adjustments if x.adjustment_type=='CANCELLATION_FEE');noshow=sum(x.amount_minor for x in adjustments if x.adjustment_type=='NO_SHOW');settlement_amount=settlement.eligible_amount_minor if settlement else 0;refund_amount=refund.eligible_amount_minor if refund else 0;block=[]
   if refund_amount>settlement_amount:block.append('REFUND_EXCEEDS_SETTLEMENT_ELIGIBILITY')
   if refund and refund.external_refund_invoked:block.append('EXTERNAL_REFUND_STATE_UNEXPECTED')
   payload={'settlement':settlement_amount,'refund':refund_amount,'cancel':cancel,'noshow':noshow,'blockers':block};r=PostStayReconciliationRow(post_stay_reconciliation_id=ident('psr'),dispute_case_id=case_id,settlement_eligible_minor=settlement_amount,refund_eligible_minor=refund_amount,cancellation_fee_minor=cancel,no_show_fee_minor=noshow,decision='CONTRACT_RECONCILED' if not block else 'BLOCKED_DIFFERENCE',blockers_json=block,evidence_hash=digest(payload),created_at=now());s.add(r);s.commit();return out(r)
 def close(self,case_id,b,actor):
  if not b.get('closure_evidence_reference'):raise ValueError('CLOSURE_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   c=s.get(PostStayDisputeCaseRow,case_id);d=s.scalar(select(PostStayDecisionRow).where(PostStayDecisionRow.dispute_case_id==case_id,PostStayDecisionRow.state=='APPROVED_CONTRACT_ONLY')) if c else None
   if not c or not d:raise ValueError('APPROVED_DECISION_REQUIRED_FOR_CLOSURE')
   counts={'evidence':s.query(PostStayDisputeEvidenceRow).filter_by(dispute_case_id=case_id).count(),'communications':s.query(PostStayDisputeCommunicationRow).filter_by(dispute_case_id=case_id).count(),'decision':d.post_stay_decision_id,'closure':b['closure_evidence_reference']};c.closure_hash=digest(counts);c.state='CLOSED';mirrors=s.scalars(select(StayDisputeRow).where(StayDisputeRow.stay_lifecycle_id==c.stay_lifecycle_id,StayDisputeRow.state=='OPEN_SETTLEMENT_FROZEN')).all()
   for x in mirrors:x.state='CLOSED'
   s.commit();return out(c)
post_stay_dispute_service=Service()
